# 簡易ADAS

車載カメラ映像または動画ファイルから、YOLOによる車両/歩行者検出、追跡、進行方向ベクトル、車線、距離推定、危険判定を行い、PySide6 UI 上にオーバーレイ表示する簡易ADASです。

## セットアップ

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/check_env.py
.venv/bin/python scripts/prepare_assets.py
```

## 起動

```bash
.venv/bin/python main.py
```

標準では Mac で扱う前提の `config/realtime_cpu.yaml` を読み込みます。品質選択は廃止し、この標準設定1本で動きます。この設定では高解像度動画も横幅 640px まで自動縮小して処理します。

`scripts/prepare_assets.py` は標準の `models/yolo11n.pt` に加えて `models/yolo26n.pt` も準備します。起動後は UI の `YOLOモデル` から `26n PyTorch (YOLO26)` を選択できます。

標準設定では、入力FPSに応じて解析を約10fpsに自動調整します。たとえば30fps動画なら3フレームに1回だけAI解析します。処理が再生予定から遅れた場合は、その回の認識だけ自動で飛ばして映像表示を優先します。解析を飛ばしたフレームでも、前回の車/人の検出枠・車線・台形ゾーン・警告は描画し続けます。YOLO は 416px、最大検出数80、信頼度0.25です。

検出された対象は `car 0.87 ID:3` のようなラベル、枠、追跡履歴、黄色の進行方向ベクトルで表示されます。ベクトル横の `v 8.1px/f` は画面上の移動量で、対向車の右左折侵入や前車発進などの判定にも使います。

カメラ設置位置や画角が違う場合は、UI 左側の台形ゾーン調整で `台形ゾーン中心`、`台形の奥行き`、`手前幅`、`カーブ寄せ` を調整してください。車線フォールバックやLDW判定の基準にも使われます。

車線検出は白線・黄線の色マスクと短い線分の統合を併用しており、実線だけでなく点線車線もできるだけ1本の車線として扱います。

UI の `File` メニューから動画ファイルまたはカメラを選択します。初回カメラ利用時は macOS の許可ダイアログが出る場合があります。

明示的に軽量設定を指定する場合:

```bash
.venv/bin/python main.py --config config/realtime_cpu.yaml
```

### Raspberry Pi 5 + AI HAT+

プロファイルの「カスタム3 (AI HAT+)」は、作成時のカスタム2の設定を基に、
物体検出をHailo-8上のYOLOv8mに切り替えます。検出モデルが変わるため、
カスタム2のYOLOX Tinyと検出結果は一致しません。車線、危険判定、描画などの処理は引き続きCPUで動きます。

Raspberry Pi 5にAI HAT+ 26 TOPS用のHailoRTとPythonバインディングを導入し、
Hailo-8向けの `yolov8m.hef` を `models/hailo8/yolov8m.hef` に配置してください。
このモデルはGit管理対象に含まれません。AI HAT+に接続できない場合はエラーを表示します。
カスタム3を選択した状態で設定を編集し、「カスタム3へ保存」で独立した設定として保存できます。

Hailo向けYOLO26を使う場合、Hailo Model Zoo v2.18のHailo-8用
`yolo26n.hef`、`yolo26s.hef`、`yolo26m.hef` を `models/hailo8/` に配置すると、
モデル選択欄から切り替えられます。YOLO26はモデル出力をCPUでデコードする
NMS不要の方式を使うため、このモデルではIoUのNMS設定は使われません。
モデルとその出力形式を混同しないよう、これらの名前を変更しないでください。
再生中はモデル欄の下にHailoの推論回数と直近のHailoRT推論時間を表示します。
表示FPSは入力FPSを上限とし、検出間隔や車線処理の影響も受けるため、
Hailoの推論時間とは別の指標です。

同じカメラ画像でn/s/mを比較するには、ほかのアプリがカメラとHailoを使っていない状態で、
次のコマンドを実行します（画像は保存されません）。

```bash
.venv/bin/python scripts/benchmark_hailo.py --camera 0 --output outputs/logs/hailo_benchmark.json
```

「カスタム4 (AI HAT+ 実験)」はYOLO26nとSCDepthV3を同じHailo-8で実行します。
`models/hailo8/scdepthv3.hef` が必要です。AI奥行き推定はサイドバーから切り替えられ、
別のチェック項目で深度画像を画面左上に表示できます。色はフレームごとに正規化され、
メートル単位の距離ではなく相対的な奥行きを示します。車線検出と車線逸脱警告は従来方式です。

AI奥行きON時は、相対的な近さ・進路の重なり・画像上の接近を融合して追加の危険判定を行い、
YOLOで分類されない障害物候補も正面・左前・右前で扱います。OFF時は従来方式です。
更新間隔はサイドバーで0.2〜1.0秒から選択できます。深度画像表示をONにすると候補と根拠も表示します。
暗所・深度不正・古い結果では判定困難としてAI由来警告を無効化します。
初期閾値は実車で校正されていません。詳細と限界は[AI奥行き融合の仕様](docs/ai_depth_risk.md)を参照してください。

「Pi 高速 (AI HAT+)」はAI奥行き推定が既定OFFで、カメラ表示と解析を別に実行します。
解析の待機画像は最新1枚に制限されます。設定画面でYOLOと車線の更新頻度、
カメラの取得幅・高さ、表示FPSを指定できます。取得値はカメラ再選択後に反映され、
要求に対応しない場合は実際の取得値と要求値を表示します。古い解析結果は非表示になります。
動画は全フレーム処理と実時間優先を選択できます。実時間優先では表示と解析を分離し、
遅れたフレームを飛ばします。全フレーム処理では従来の処理ループを使用します。
Pi 高速の推論は専用ワーカーで実行し、HailoRTの非同期APIは使用していません。
フレーム飛びを伴う追跡・速度・警告の時間精度については追加検証が必要です。

## 現状

- Phase 0-5 はアプリ内で一通り接続済みです。
- YOLO/ByteTrack は標準で `models/yolo11n.pt` を利用し、UI から `models/yolo26n.pt` を含む複数モデルに切り替えできます。失敗時は無検出または簡易追跡にフォールバックします。
- 路面セグメンテーションは `models/segformer-b0-cityscapes`、単眼深度は `models/depth-anything-v2-small-hf` を利用し、モデル資産が未準備でも軽量フォールバックで動きます。
- 日本標識・信号と視認性補正は、現在の標準UI/標準パイプラインから外しています。

## 評価

```bash
.venv/bin/python scripts/evaluate_alerts.py data/videos/test.mp4 --max-frames 300
```

結果は `outputs/logs/alerts.jsonl` に出力されます。

実動画がまだ無い場合は、合成デモ動画でパイプラインを確認できます。

```bash
.venv/bin/python scripts/create_demo_video.py --output data/videos/demo_synthetic.mp4
.venv/bin/python scripts/evaluate_alerts.py data/videos/demo_synthetic.mp4 \
  --config config/realtime_cpu.yaml \
  --output outputs/logs/demo_alerts.jsonl \
  --annotated-output outputs/recordings/demo_annotated.mp4 \
  --max-frames 120
```

注釈付き動画は `outputs/recordings/demo_annotated.mp4` に出力されます。

処理時間を改善する際は、同じ動画・同じ設定でステージ別の p50/p95 を比較します。

```bash
.venv/bin/python scripts/profile_pipeline.py data/videos/test.mp4 \
  --config config/realtime_cpu.yaml \
  --max-frames 300 \
  --output outputs/logs/pipeline_profile.json
```

出力JSONには全体処理時間と、検出・追跡・車線・危険判定・描画など各ステージの平均、p50、p95が含まれます。

`Plan A of 20260712` の車線評価では、実走動画の注釈付きフレームから車線検出率と自車レーン中心誤差を記録します。注釈は処理解像度座標のJSONで保持します。

```bash
.venv/bin/python scripts/evaluate_lanes.py data/videos/drive.mp4 \
  data/annotations/drive_lanes.json --config config/custom.yaml \
  --output outputs/logs/lane_evaluation.json
```

USBカメラのレンズ歪みを補正する場合は、チェスボードを異なる距離・角度で8枚以上撮影して校正値を生成し、出力された`camera_matrix`と`distortion_coeffs`をカスタムプロファイルの`lane`へ設定します。

```bash
.venv/bin/python scripts/calibrate_camera.py 'data/calibration/*.jpg' \
  --pattern 9x6 --square-mm 25 --output outputs/logs/camera_calibration.json
```

## モデルとデータ参照元

- YOLO11: https://docs.ultralytics.com/models/yolo11/
- YOLO26: https://arxiv.org/abs/2606.03748
- SegFormer Cityscapes: https://huggingface.co/nvidia/segformer-b0-finetuned-cityscapes-1024-1024
- Depth Anything V2 Small HF: https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf
- Mapillary traffic signs: https://help.mapillary.com/hc/en-us/articles/360003021432-Exploring-traffic-signs

## ライセンス注意

Ultralytics YOLO のコードと事前学習済みモデルは、既定で AGPL-3.0 の対象です。商用・非公開利用を想定する場合は、Ultralytics Enterprise License などの代替を確認してください。
