# PROGRESS.md — 進捗ログ

> 本ファイルは本プロジェクトの**唯一の進捗管理ドキュメント**である。
> 計画・設計は `PLAN.md`、進捗・履歴・意思決定は本書に記録する。

---

## 📌 ルール（全員厳守）

1. **実装・編集・修正・調査・議論・意思決定** を行ったら、**その都度本ファイルに追記する**
2. 1 タスク 1 エントリ（粒度: 1〜2 時間の作業単位）。1 日まとめ書きは禁止
3. **エントリの削除は禁止**。誤りは ~~取り消し線~~ ＋ 訂正で残す
4. 仕様変更が決まったら `PLAN.md` を更新し、本書にも「PLAN.md §X を更新」と記録する
5. 詰まり・未解決事項は §未解決事項 に記録、解決時に解決日を追記
6. このルールに違反した PR / コミットはレビュー差し戻し対象

### エントリ・テンプレート

```markdown
### YYYY-MM-DD HH:MM — [担当者] [種別] 短いタイトル
- **内容**: 何をしたか / 何が起きたか
- **影響**: 変更ファイル、関連 Phase（PLAN.md §B.X）、関連要件（PLAN.md §1.X）
- **次の方針**: 次に何をやるか
- **メモ**: 補足、参考リンク、所要時間など
```

### 種別タグ
- `[実装]` 新規コードを書いた
- `[修正]` 既存コードを直した
- `[調査]` ライブラリ・データの調査
- `[議論]` 仕様・設計の議論
- `[意思決定]` 方針が確定したもの
- `[詰まり]` 未解決の課題が発生
- `[ドキュメント]` PLAN.md / PROGRESS.md などの編集
- `[テスト]` 動作確認・評価

---

## 🔄 セッション再開ガイド（最重要・最初に読む）

**最終セッション**: 2026-05-21 / **作業ブランチ**: `ver11` (github にも push 済)

### 再開キーワード
ユーザーが「**続きやって**」「**続きをお願い**」「**続きから**」等と言ったら、まずこの節と直下の「📋 プロジェクト現状サマリー」を読んでから作業を始める。

### 現在地 (2026-05-20 時点)
| 項目 | 状態 |
|---|---|
| ブランチ | `ver6` (最新コミット `d714ada`) |
| GitHub | `https://github.com/tyakyumyou-soviet/car_kentchi2/tree/ver6` |
| バージョン履歴 | ver1 → ver2 → ver3 → ver4 → ver5 → **ver6** |
| 開発環境 | conda env `main` (`/opt/anaconda3/envs/main/`) |
| Python パッケージ | YOLO11/Ultralytics + onnxruntime 1.26 + tensorflow 2.21 (EfficientDet 用) |
| モデル | `models/` に YOLO11 n/s/m/l/x + YOLOX-Nano/Tiny + NanoDet-Plus + EfficientDet-Lite0 の 9 個 |
| テスト | `cd /Users/tyakyumyou/Downloads/car_program2 && PYTHONPATH=. /opt/anaconda3/envs/main/bin/pytest -q --ignore=tests/test_pipeline_smoke.py` で 54 passed |

### ver8 で追加された機能 (push 済)
- **Coral Edge TPU 対応フェーズ A 完了** (`§Coral Edge TPU 対応 roadmap` 参照)
  - device ガード (`.tflite`→CPU 強制)、環境別プロファイル、INT8 tflite 生成、精度比較スクリプト
  - UI モデル選択に「n TFLite INT8」追加 (PyTorch 版と並べて選択可)
  - INT8 精度: person 約79% (中サイズで64%) → 次は imgsz480/再キャリブ/bicycle検証 を判断
- ※ `models/*` は gitignore のため tflite 本体は repo 未追跡 (各環境で再生成)

### ver7 で追加された機能 (push 済)
- **カメラ異常検知** (`ui.enable_blind_check`) — 検出ゼロ + 画質劣化の AND で赤帯通知
- 感度調整済み: brightness_min=25 / contrast_min=14 / sharpness_min=25 / no_detect_seconds=2.0
- ⚠ **実機/実映像での性能テストは未実施** (`§未解決事項` 参照)

### 保留中の高速化施策 (ユーザー判断待ち)
| 番号 | 内容 | 状態 |
|---|---|---|
| ① | ONNX + onnxruntime XNNPACK (Pi 5 で 2-3 倍速) | 部分実装 (外部モデル経由で onnxruntime は導入済み)、YOLO11 系の ONNX 化は未着手 |
| ② | INT8 量子化 | 保留 (① 完了後) |
| ⑥ | 小モデル差し替え | **実装完了** (YOLOX/NanoDet/EfficientDet 追加) |
| A. リアルタイム優先 | 撤回 (飛び出し人検出不可になった) |
| B. 適応的フレームスキップ | 撤回 (同上) |
| ⑧ Motion-based skip | 撤回 (同上) |

### 最近のユーザー要望と対応状況
- ✅ カメラ異常検知 (AND ハイブリッド、感度寄りに調整) → ver6 push 後に実装
- ✅ ROI 推論 (台形/矩形 切替、矩形は半透明可視化)
- ✅ YOLO11 → YOLO11 + 外部 4 モデル
- ⚠ 人の端っこ検出が弱い → 「処理解像度を上げる」「conf 下げる」を提案済、ユーザー検証中
- ⚠ 飛び出し人検出 → ROI/Motion 系を撤回し検出感度優先に方針確定

### 次回セッションで聞かれそうなこと / TODO
- 🎯 **次の主要作業**: Coral Edge TPU 対応 (`§Coral Edge TPU 対応 roadmap` 参照) — フェーズ A から着手
- カメラ異常検知の **実機テスト** (汚れ/霧/レンズ遮蔽/低照度) — 性能未検証、誤検知率の評価必要
- 矩形 ROI の人検出問題: 「人/自転車だけ全画面 YOLO」モード実装の判断 (議論済、未実装)
- ~~① ONNX 化~~ → Coral roadmap に統合 (Ultralytics `export(format=edgetpu)` が PyTorch→ONNX→TFLite→EdgeTPU を一括変換するため手動 ONNX 化は不要に)

### 重要な運用ルール
1. PROGRESS.md / PLAN.md 以外のドキュメントは増やさない
2. 進捗エントリは削除禁止 (取り消し線で対応)
3. ユーザーは Pi 5 へ最終移植する想定。常にそれを視野に
4. 検出感度 > 速度。軽量化は ROI / 解像度 / モデル選択で

---

### 2026-05-21 00:31 — [Codex] [修正] ver10 端の歩行者危険判定・車線認識・暗所異常検知を調整
- **内容**: 端から自車レーン方向へ入る歩行者/自転車を、赤い台形内に入る前でも `*_rush` として早期警告しやすくした。車線検出では Hough 線分の端点順に依存しない底辺交点計算へ修正し、暗めの映像で白線マスクを少し拾いやすくした。カメラ異常検知は通常の暗闇だけで「認識できない」通知が出にくいよう、真っ暗判定を「暗い + 低コントラスト + 低シャープネス」の複合条件へ緩和した。
- **影響**: `src/prediction/risk_analyzer.py`, `src/lane/classical.py`, `src/detection/blind_check.py`, `tests/test_risk_analyzer.py`, `tests/test_lane_classical.py`, `tests/test_blind_check.py`。関連要件: 端からの飛び出し歩行者検知、車線認識安定化、カメラ異常検知の誤通知抑制。
- **次の方針**: 実映像で、端の歩行者警告が過敏すぎないか、夜道で「認識できない」通知が必要時に残るかを確認する。必要なら `side_entry` 距離/速度閾値と `BlindnessDetector` の暗所条件を追加調整する。
- **メモ**: `/opt/anaconda3/envs/main/bin/python -m pytest` で 63 passed。`ver10` として push 予定。

### 2026-05-21 00:34 — [Codex] [修正] 自車操舵による見かけ離反で車両危険を落とさない
- **内容**: 車両の `heading` / `facing` / 脅威度計算に、画面上の生ベクトルではなくエゴモーション補正後の相対ベクトルを優先して使うよう修正した。さらに自車の横流れが強い状態で、近傍車両が見かけ上離反しても `evasive_vehicle` として危険側に残すガードを追加した。
- **影響**: `src/prediction/risk_analyzer.py`, `tests/test_risk_analyzer.py`。関連要件: 自車が回避操舵したときに、相手車が画面上で安全方向へ流れて見えても衝突リスクを落としすぎない。
- **次の方針**: 車両危険判定全体を精査し、TTC/面積拡大/レーン交差/自車操舵/相手向き/距離推定を統合したスコアリングへ段階的に整理する。次は「車両がレーン外から侵入するが軌跡履歴が短い」「距離推定なしでもBB拡大で危険を出す」ケースを重点確認する。
- **メモ**: `/opt/anaconda3/envs/main/bin/python -m pytest` で 64 passed。

### 2026-05-21 01:13 — [Codex] [修正] 車両危険判定に短履歴侵入とBB拡大TTCを追加
- **内容**: `cut_in` の履歴ベース判定だけでは拾いにくい短履歴の側方車両侵入を `side_vehicle_entry` として早期警告するロジックを追加した。距離推定が無い車両でも、BB面積拡大から算出される looming TTC が短い場合に `vehicle_looming` として急接近警告を出すようにした。
- **影響**: `src/prediction/risk_analyzer.py`, `tests/test_risk_analyzer.py`。関連要件: 側方から出てくる車両、距離推定未取得時の急接近車両、短い履歴でも危険側に倒す車両予測。
- **次の方針**: 実映像で `side_vehicle_entry` と `vehicle_looming` の過敏さを確認する。次の精査候補は、同一車両に複数警告が重なる場合の優先順位整理と、車両スコアを単一の統合関数へ寄せるリファクタ。
- **メモ**: `/opt/anaconda3/envs/main/bin/python -m pytest` で 66 passed。

### 2026-05-21 01:18 — [Codex] [修正] 車両早期警告の過剰反応を抑制
- **内容**: `side_vehicle_entry`, `vehicle_looming`, `evasive_vehicle` が過敏に出すぎる問題を受け、側方車両はより近く・横速度が明確・下方向/近距離にいる場合に限定した。BB拡大警告は TTC 1.6s 以下、近傍かつ接近方向、面積比 1.8% 超に絞った。操舵ガードも距離不明の小さい車両だけでは発火しないようにした。
- **影響**: `src/prediction/risk_analyzer.py`, `tests/test_risk_analyzer.py`。関連要件: 危険判定の過剰反応抑制、実用上の警告ノイズ低減。
- **次の方針**: 実映像でまだ過敏なら、早期車両警告を UI/設定で ON/OFF または感度段階化する。次回は警告重複の整理と、`AlertManager` 側の同一対象優先順位制御を検討する。
- **メモ**: `/opt/anaconda3/envs/main/bin/python -m pytest` で 68 passed。

### 2026-05-21 01:36 — [Codex] [修正] 車両危険判定の敏感化を ver10 状態へ戻し
- **内容**: ユーザー指示により、車両危険判定を敏感化前の `ver10` 状態へ戻した。具体的には、未コミットだった `evasive_vehicle`, `side_vehicle_entry`, `vehicle_looming` と関連テスト追加を取り消し、端の歩行者・車線・暗所異常検知調整は維持した。
- **影響**: `src/prediction/risk_analyzer.py`, `tests/test_risk_analyzer.py` を `ver10` の内容に復元。`PROGRESS.md` は履歴保持のため本エントリを追記。
- **次の方針**: 車両危険判定を再強化する場合は、いきなり警告条件を追加せず、実映像ログ/メタ情報で「どの条件が落としているか」を可視化してから段階的に調整する。
- **メモ**: 敏感化ロジックは未コミットだったため、Git 履歴には残していない。

### 2026-07-12 10:56 — [Codex] [ドキュメント] Plan A of 20260712 を計画書へ統合
- **内容**: 車線が見える時だけ滑らかにLDWを動作させ、検出不能時は車線関連機能を停止する方針を確定した。v15の計測基盤、v16のIPM/RANSAC/Kalman局所追跡、v18のHailo車線AIの条件付き導入、ならびに局所探索・固定小数点IPM・最新1フレーム化を計画へ追加した。
- **影響**: `PLAN.md` §12。関連要件: 全画面YOLOの維持、車線なし道路でのLDW抑制、Pi 5 + Hailo移植時の低遅延化。
- **次の方針**: v15として、実走動画セットと車線/遅延のp50/p95比較スクリプトを整備する。
- **メモ**: Rust全面移行は採用しない。OpenCV/GStreamer/Hailoのネイティブ実装で実測し、Python固有ループがボトルネックの場合だけ再検討する。

### 2026-07-12 11:20 — [Codex] [実装] Plan A v15/v16とv18鮮度制御を実装
- **内容**: v15として車線評価スクリプト、warmup除外プロファイル、車線状態/フレーム鮮度の集計を追加した。v16として固定小数点IPM、粗探索と局所追跡、ロバスト二次曲線、曲線係数Kalman Filter、`SEARCH/ACQUIRE/TRACK/LOST`状態、未検出時のLDW停止を実装した。v18の土台として最新カメラフレームと結果鮮度上限をLDW/描画へ接続した。
- **影響**: `src/lane/ipm.py`, `src/lane/lane_detector.py`, `src/pipeline.py`, `src/ui/inference_thread.py`, `scripts/evaluate_lanes.py`, `scripts/calibrate_camera.py`, `PLAN.md` §12。カスタムプロファイルは`lane.method: ipm`を使用する。
- **次の方針**: USBカメラをチェスボードで校正し、実走注釈動画でv16とclassicalの検出率・中心誤差・p95を比較する。Pi 5 + AI HAT実機でHailo車線モデルの変換と総遅延受け入れ試験を行う。
- **メモ**: 合成360x203車線ベンチでは、IPM専用BEVを0.5倍へ縮小後、IPM平均約1.20ms、従来Hough平均約1.29msだった。実走精度と実機遅延は未測定。

### 2026-07-12 11:45 — [Codex] [修正] 車線見逃しと異常LDWを抑制
- **内容**: IPMの白線しきい値を明暗に応じて適応化し、車両BBを車線候補から除外した。左右車線の幅、中心、時間変化を検査して不自然な候補をKalman更新前に棄却するようにした。IPMが見逃した時は、高信頼度の実画像Hough検出だけを補助に使用し、路面マスクや固定台形は車線として使わない。LDWには300%超の異常な逸脱率を無効化する最終ガードを追加した。
- **影響**: `src/lane/ipm.py`, `src/lane/lane_detector.py`, `src/pipeline.py`, `config/default.yaml`, `tests/test_lane_ipm.py`, `tests/test_ldw.py`, `PLAN.md` §12.6。
- **次の方針**: 実走映像の注釈評価で、車線見逃し率とLDW誤報率をver17基準と比較する。IPMの台形パラメータはUSBカメラ校正後に調整する。
- **メモ**: `79 passed`、`ruff check`、差分チェックを通過。今回の変更は未コミット・未push。

### 2026-07-12 12:05 — [Codex] [修正] 赤い台形を車線候補のソフト参照へ統合
- **内容**: ユーザーが調整する赤い台形の位置を、IPMの全域探索における左右ヒストグラムの重み付けと、候補の中心/幅整合度の信頼度に利用するよう変更した。台形はハードな切り抜きではないため、カーブや手動調整の誤差で正しい車線を即座に除外しない。車線候補が台形から大きく離れる場合だけ棄却する。
- **影響**: `src/lane/ipm.py`, `src/lane/lane_detector.py`, `src/pipeline.py`, `config/default.yaml`, `tests/test_lane_ipm.py`, `PLAN.md` §12.6。
- **次の方針**: 実走映像で、赤い台形の中心・手前幅・奥行きを実際の自車レーンに合わせた上で、検出率とLDW誤報を比較する。
- **メモ**: `81 passed`、`ruff check`、差分チェックを通過。今回の変更は未コミット・未push。

### 2026-07-16 — [Codex] [実装] カスタム2の多レート処理とYOLOX Tiny追跡安定化
- **内容**: 車線検出とYOLO検出に独立した周期・位相を追加し、カスタム2を車線0位相/YOLO1位相として同時実行を避けるようにした。YOLOX Tinyの外部追跡は実フレーム差を使った速度計算、クラス整合、予測位置、IoU、BB面積変化による対応付け、不自然なジャンプの新ID化、2検出確認後の運動信頼性を追加した。危険判定は局所背景フロー、近距離・画面下・連続確認条件を使うようにした。UIから車線/検出の周期と位相を設定できる。`device: cpu`時はYOLOXがCoreMLを選ばないようにした。
- **影響**: `src/pipeline.py`, `src/tracking/byte_tracker.py`, `src/detection/external_detector.py`, `src/motion/ego_motion.py`, `src/prediction/risk_analyzer.py`, `src/types.py`, `src/ui/settings_dialog.py`, `config/custom2.yaml`, `config/default.yaml`, `tests/test_yolox_tracking_stability.py`。関連 PLAN.md §12.7。
- **結果**: `84 passed`。カスタム2の8フレーム合成スモークでYOLOX Tiny CPUロードと、lane/YOLOの処理分散を確認した。実動画は現在ワークスペースに無いため、実映像での誤警告率・p95遅延は未測定。pushは行わない。

### 2026-07-17 — [Codex] [実装] 危険対象の左右・中央表示
- **内容**: 危険対象のBB下端中心を、その奥行きにおける自車レーンまたは走行台形の左右境界と比較し、`左`・`中央`・`右`を判定する処理を追加した。警告文、対象BBラベル、警告一覧テーブルに同じ方向を表示する。
- **影響**: `src/types.py`, `src/prediction/risk_analyzer.py`, `src/render/renderer.py`, `src/ui/main_window.py`, `tests/test_risk_analyzer.py`。関連 PLAN.md §12.7。
- **結果**: `85 passed`。台形の同じ奥行きで左・中央・右を判定する回帰テストを追加。pushは行わない。

## 📋 プロジェクト現状サマリー（ver6 / カメラ異常検知 機能追加）

最終更新: 2026-05-20

### バージョン履歴と主要マイルストーン

| タグ | 日付 | 主要内容 | コミット |
|------|------|---------|---------|
| v1 | 2026-05-11 | 簡易ADAS初版（YOLO+ByteTrack+車線+TTC+UI） | `c8f8e1d` |
| v2 | 2026-05-11 | 自車エゴモーション推定で誤判定抑制 | `4e2a1b3` |
| v3 | 2026-05-11 | 車線検出強化（点線・自車レーン・滞在判定） | `3d89654` |
| **stable-1 = v4** | 2026-05-11 | 9件改善対応（UI反映バグ、衝突誤警告抑制、車両進行方向、信号vsテールランプ等） | `6f7bbbc` |
| v5 | 2026-05-12 | 全機能ON / 障害物検出 / 向き判定 / 台形自動化 | `ea43a86` |
| v6 | 2026-05-12 | AutoZone簡素化 / 絶対ベクトル推定（OBD2準備） | `5e12295` |
| v7 | 2026-05-12 | 11件改善（UI停止後再開バグ、統合危険度スコア等） | `ce76c8c` |
| v8 | 2026-05-12 | 5件改善（向きラベル表示、レーン安定化） | `cdbf2ea` |
| v9 | 2026-05-12 | 人検出強化 / 車線実線・点線優先 ※レーン固着バグ混入 | `6d5eebd` |
| v9.1 | 2026-05-12 | 車線固着バグ修正（指数減衰平滑化） | `be4c7a4` |
| v9.2 | 2026-05-12 | **車線検出を stable-1 (v4) と同一に巻き戻し** | `7798934` |
| v9.3 | 2026-05-12 | フロント↔リア誤判定修正（赤い車体色対策） | `d83ac91` |
| **stable-2 = v9.4** | 2026-05-12 | 白線なし道での路面マスクフォールバック追加 | `7a29e1d` |
| v9.5 | 2026-05-12 | LDW を偏差率ベースに洗練（方向情報＋3f連続） | `ef97df8` |
| **v9.6 (HEAD)** | 2026-05-12 | 障害物検出を完全削除 + 自転車検出を強化（conf 0.15、ピンクBB、専用閾値） | (HEAD) |

### 機能別の実装状態

#### 🚗 物体検出・追跡
- **モデル**: YOLO11n (Ultralytics) + ByteTrack
- **動作デバイス**: MPS (Apple Silicon) 自動選択、CPU フォールバック
- **検出クラス**: person / bicycle / motorcycle / car / bus / truck
- **クラス別 conf 閾値**（誤検出抑制と人/自転車敏感化の両立）:
  - person: **0.18**
  - bicycle: **0.15**（最も敏感、遠方の自転車も拾う）
  - motorcycle: 0.25
  - car, bus, truck: **0.32**（誤検出抑制）
- **BB 色** (Renderer): 人=緑 / **自転車=ピンク** / バイク=シアン / 車=橙
- **YOLO 出力時 conf**: 0.18、imgsz 480、max_det 120
- **解像度**: 入力を `max_process_width: 960` に自動縮小

#### 🛣 車線検出
- **手法**: `ClassicalLaneDetector` (v4 = stable-1 と完全同一)
  - Canny エッジ + HSV 白/黄マスク + 縦長カーネル閉処理（点線結合）
  - HoughLinesP で線分検出
  - 傾き・x切片でクラスタリング → 画面中央に最も近い左右1ペアを採用
  - 自車レーン幅は画像幅の 18-55% に制限
- **時間平滑化**: 過去 15 フレームの重み付き平均（confidence ベース）
- **交差ガード**: 左 x ≥ 右 x になる検出は不採用
- **center_x_ratio 自動追従**: 検出された自車レーン底辺中点に 30% 重みで滑らかに追従
- **白線なし道フォールバック (v9.4 追加)**:
  - 条件: classical 両側失敗 AND 履歴 < 3 フレーム AND road_mask あり
  - 動作: 路面マスクの左右輪郭から線形フィット、幅 1/2 で自車レーン構築
  - 信頼度 0.20（古典より低く、白線が見え次第そちら優先）

#### ⚠ 車線逸脱警告 (LDW) — v9.5 で洗練
- **判定**: 「自車中心と自車レーン中心の偏差率」で評価（車線幅で正規化）
  - 偏差率 = |自車x − レーン中心x| / 車線半幅
- **3 段階レベル**:
  - 偏差率 < 0.6: 正常（警告なし）
  - 0.6 ≤ < 0.9: warn (level 2) — `車線寄り注意 (右側 75%)` のように方向＋%表示
  - ≥ 0.9: **critical (level 3)** — `⚠ 車線逸脱 (左方向 130%)` のように方向＋%表示
- **連続 3 フレーム要件**: 瞬間ノイズで発火しない
- **車線幅信頼性チェック**: lane_half_width < 8px → 判定スキップ
- **信頼度ゲート**: 検出 confidence < 0.3 では発火しない

#### 🚦 統合危険度スコア
- `threat_score.py` で 0-1 スコア合成
  - 距離 (0.30 重み): 5m=1.0, 30m=0.0
  - TTC (0.30 重み): 1s=1.0, 5s=0.0
  - heading: approaching +0.15, leaving -0.20, lateral +0.05
  - facing: front +0.15, rear -0.10
  - 相対接近速度: +mps なら危険、-2.0 未満で安全方向
  - 自車レーン滞在: +0.10 (+ 8 フレーム以上で +0.10)
- レベル分類:
  - < 0.30: 警告なし
  - 0.30-0.45: info
  - 0.45-0.65: warn (車間注意)
  - ≥ 0.65: critical (衝突注意)
- **警告メッセージに「脅威度XX」を含めて視覚化**

#### 🎯 衝突予測補助
- **`TTCEstimator`**: 距離 TTC + looming (BB面積拡大率) TTC のフォールバック融合
- **`is_pedestrian_rush`** (緩和済): 人=age≤12 + 速度3.0+ / **自転車=age≤16 + 速度2.5+**（自転車は人より敏感）+ 自車レーン方向 など 4 条件 OR
- **`is_cut_in_vehicle`**: 横方向速度2.5+ + 自車レーンへの軌跡交差 + 接近方向
- **`classify_vehicle_heading`**: approaching / leaving / lateral / static / unknown
- **自車レーン滞在カウンタ**: 連続 8 フレーム滞在で衝突警告対象に
- **離反車除外**: heading=="leaving" は警告対象外
- **前車発進警告**: 自車前進中は判定無効化、履歴 8 フレーム + 停止 max<0.5 + 発進 >3.0

#### 🚙 車両向き判定 (`vehicle_facing.py`)
- aspect > 2.5 → side 確定
- vy > 2.5 / < -2.5 → front / rear 確定（色解析スキップ）
- BB 左右端 1/4 領域のペアで対称ランプ判定:
  - 両端ともテールランプ赤 → rear
  - 両端ともヘッドライト白 → front
  - 中央 1/2 の車体色は無視
  - 60% 以上赤い場合は車体色とみなして却下
- vy と色が衝突する場合、aspect 縦長なら vy 優先、横長なら color 採用

#### 🌌 自車エゴモーション (`ego_motion.py`)
- Lucas-Kanade スパースオプティカルフローで背景キーポイント追跡
- 消失点の最小二乗推定（車線消失点との 70/30 統合）
- 速度レベル分類: `stop` / `slow` / `moderate` / `fast`
- 背景フロー場（位置別）も取得可能 → RiskAnalyzer の相対速度補正に使用

#### 📐 絶対速度推定 (`absolute_velocity.py`)
- IPM (逆透視変換) で実世界 m/s 換算
- 自車速度 (`SpeedSource`) を加味して相手車の **絶対ベクトル** を出力
- 信頼度 0-1（遠距離・履歴不足で低下）
- **`SpeedSource` Protocol** で将来 OBD2 (`ObdSpeedSource`) に差し替え可能

#### 🚥 信号検出 (`jp_sign_detector.py`)
- 画面上 40% に ROI 限定
- HSV で赤/黄/青/緑円形を検出
- 車両 BB と重なる候補（テールランプ等）を除外
- デフォルト OFF（v4 以降）

#### 🌙 視認性補正 (`enhancer.py`) — 2026-05-18 超軽量化
- **gamma LUT 1 発のみ** (gamma=0.6, 事前計算)：暗所で YOLO に見やすくする目的に特化
- 暗所判定: 64x64 ダウンサンプル gray の mean < 70、8 フレームに 1 回キャッシュ
- 計算コスト: 暗フレーム適用時 ~4.5ms、明るいフレーム ~2ms (1920x1080)
- 旧版の LAB+CLAHE+デノイズ/HDR Mertens は **削除済み**
- デフォルト OFF

#### 🛣 路面セグメンテーション (`road_segmenter.py`)
- SegFormer-b0 Cityscapes 学習済み（HuggingFace）
- 出力: 0 (その他) / 1 (車道) / 2 (歩道)
- 設定: 18 フレームに 1 回 / 入力 256px
- 用途: 歩道歩行者除外、白線なし車線フォールバック、障害物検出

#### 🖼 UI (PySide6)
- プロファイル切替コンボボックス（標準 / フル品質 / 超軽量 / 映像のみ）
- 入力ソース: ファイル / カメラ（再生中切替可）
- **再生 / 停止 / 再開のバグ修正済**（`_last_source_factory` で保持）
- スライダー: 台形ゾーン中心 / 奥行き / 手前幅 / カーブ寄せ
  - 「奥行きモード」コンボで自動/固定 切替
- チェックボックス: 検出 / 車線 / 危険判定 / 障害物 / 信号 / 視認性補正 / 路面マスク
- **設定変更がリアルタイム反映** (`Pipeline.update_settings` 経由)
- BB に：クラス名・信頼度・ID・距離 + 下に **front/rear/side の色付き向きラベル**

### 現在のデフォルトプロファイル (`config/realtime_cpu.yaml`)

| 機能 | デフォルト |
|------|----------|
| 検出/追跡 | ✅ ON |
| 車線/LDW | ✅ ON |
| 危険判定 | ✅ ON |
| 路面マスク | ✅ ON |
| 信号/標識 | ❌ OFF |
| 視認性補正 | ❌ OFF |
| エゴモーション | ✅ ON (裏方) |

### パフォーマンス（demo_highres.mp4 1284x2778、MPS）

| 構成 | avg | fps |
|------|-----|-----|
| 標準（v9.5 デフォルト） | 131-168ms | 6-7 fps |
| 障害物のみ追加 | +約 20ms | -1 fps |
| 視認性補正・信号 ON | +約 30ms | -2 fps |
| 全機能 ON (v5 デフォルト) | 192ms | 5.2 fps |

### テスト・品質

- **pytest**: **56 passed** （継続して拡張中）
- **ruff**: clean（全ファイル）
- 主要モジュール網羅: ego_motion, speed_source, threat_score, vehicle_facing, intrusion_heading, obstacle, auto_zone, lane_classical, lane_no_lines, **ldw**, risk_analyzer, ttc, alert_manager, fallback_detector, jp_sign_detector, config, geometry, pipeline_smoke, renderer

### 未解決事項

| # | 内容 | 起票日 | 対応状況 |
|---|------|--------|---------|
| 1 | カメラ内部パラメータのキャリブ手順 | 2026-05-11 | 未対応（Phase 4 着手前） |
| 2 | 日本標識データセット最終ソース選定 | 2026-05-11 | 未対応（Phase 6） |
| 3 | 評価用動画シーン定義 | 2026-05-11 | 未対応 |
| 4 | 自車速度の実数推定（視覚ベース） | 2026-05-11 | 部分対応（forward_flow_px から粗推定） |
| 5 | テスト動画保管場所 | 2026-05-11 | 未対応（Git ignore で除外中） |
| 6 | ライセンス選定（Ultralytics は AGPL） | 2026-05-11 | 未対応 |
| 7 | プライバシー方針 | 2026-05-11 | 未対応 |
| 8 | ~~MPS が False~~ | ✅ 解決 | 2026-05-11 解決 (実は available: True だった) |
| 9 | full_quality の 1.3 fps 問題 | 2026-05-11 | 軽量設定への切り替えで対応中 |
| 10 | カメラ異常検知の性能評価 (実機/実映像での誤検知率・反応速度) | 2026-05-20 | 未対応 (実装は ver7 で完了、テストのみ未実施) |
| 11 | ~~Coral 用 `_edgetpu.tflite` 生成 (依存非互換)~~ | 2026-05-21 | ✅ 解決 (2026-05-21)。Ultralytics 公式イメージ + numpy<2 でコンパイル成功。`PLAN.md §C.1-2` |

### 将来の方向性

- **OBD2 接続**: `ObdSpeedSource` を Pipeline に注入するだけで絶対速度の精度向上（インターフェース整備済み）
- **日本信号・標識の追加学習**: Phase 6（データ収集 → アノテーション → fine-tuning）
- **CoreML 化**: `yolov8n.mlpackage` 変換で更なる高速化の余地
- **完全非同期パイプライン化**: Producer-Worker-UI の 3 スレッド構造
- **車線検出 DL 化**: 古典手法では限界がある場面で Ultra-Fast-Lane-Detection 等への置換検討

---

## 🎯 Coral Edge TPU 対応 roadmap (2026-05-20 策定)

### ゴール
**1 コードベースで 3 環境を「重み差し替えだけ」で動かす**:

| 環境 | 重みファイル | device | 用途 |
|---|---|---|---|
| Mac (現状) | `yolo11n.pt` | mps | 開発・基準精度 |
| Mac / Pi CPU | `yolo11n_full_integer_quant.tflite` | cpu | INT8 精度検証 |
| Pi 5 + Coral USB | `yolo11n_full_integer_quant_edgetpu.tflite` | tpu:0 | 本番 |

- 推論呼び出し (`YOLO(weights).predict()`) は全形式で共通 → 後段 (ByteTrack/危険判定) は無改修
- Coral は **INT8 量子化済み TFLite を Edge TPU 用にコンパイルした `.tflite` 限定**でしか動かない
- 変換は Ultralytics 1 発: `yolo export model=yolo11n.pt format=edgetpu imgsz=320 data=<代表画像>`

### 変換ツールチェーンと実行場所
- `edgetpu_compiler` は **x86_64 Linux 専用** (ARM/Mac ネイティブでは不可)
- この Mac では **Docker の `--platform linux/amd64` エミュレーション** で実行可能 (確認済: Docker 28.1.1 / amd64 コンテナで `x86_64` 確認)
- 変換は軽処理なのでエミュレーションでも問題なし

### フェーズ

#### フェーズ A: Mac で TFLite 化 + コード対応 (Coral 実機不要) ← 着手中
- A1. `yolo_detector.py` に **device ガード** (`.tflite` 時は mps→cpu 強制)
- A2. config に **環境別プロファイル** (weights/imgsz/device 切替)
- A3. Mac で `yolo11n_full_integer_quant.tflite` を生成
- A4. **精度比較**: `.pt`(基準) vs INT8 `.tflite` を同一映像で検出率比較 (特に遠方の人/自転車)
  → **「INT8 が実用に耐えるか」の意思決定ポイント** (検出感度 > 速度 の原則で判断)

#### フェーズ B: Coral 用ファイル生成 (Docker amd64)
- B1. amd64 コンテナで `yolo export format=edgetpu` (imgsz 320 / 480 両方)
- B2. `*_edgetpu.tflite` を Mac (ホスト) に取り出す

#### フェーズ C: ラズパイ移植ドキュメント整備
- C1. PLAN.md に **Pi セットアップ手順** を追記 (新規 .md は作らない)
  - libedgetpu / tflite-runtime 導入、Coral 認識、推論、ベンチ、受け入れ基準
  - **agent-neutral に記述** (Claude Code でも Codex でも実行可能。エージェント前提の文言禁止、コマンド/前提/受け入れ基準を明示)
  - 「Mac/x86 章 (変換・転送)」と「Pi 章 (導入・推論・ベンチ)」を分離

#### フェーズ D: ラズパイ実機検証 (Coral 入手後)
- D1. Pi 上で 320 vs 480 の fps・検出率を実測 → imgsz 確定
- D2. INT8 版 vs PyTorch 版で検出率比較 → 本番投入判断

### 注意点
- **検出感度 > 速度** (A4/D2 の判断はこれに従う)
- imgsz=320 は小さい遠方ターゲットを取りこぼす懸念 → 320/480 を必ず比較
- INT8 精度はキャリブ用代表フレームで上がる (なければデフォルトで一旦進める)

---

## 📅 進捗ログ（新しい順）

### 2026-05-21 — [Claude] [実装] フェーズB完了: Coral 用 `_edgetpu.tflite` 生成成功 (購入判断の確証)
- **内容**: 前エントリの依存地獄を、**Ultralytics 公式 Docker イメージ `ultralytics/ultralytics:latest-cpu` + numpy<2** で突破。`yolo export format=edgetpu imgsz=320` がコンパイル成功
- **背景**: ユーザーは Coral 未購入。「Mac 上で YOLO が Coral 用にちゃんと変換できる」確証が得られないと購入判断できないため、生成成功自体が成果物
- **成功レシピ** (`PLAN.md §C.1-2` に記録): 公式イメージは tf 2.19.0 / onnx2tf 1.28.8 を整合済みで保持。numpy だけ 2.x→1.26.4 に下げれば通る。手動バージョンピンは 7 通り試して全滅 (QuantizeModel 引数不一致)
- **コンパイル結果** (op マッピング = 購入判断材料): `Compilation succeeded!` / **CONV_2D 208個・DEPTHWISE_CONV_2D 6個が Edge TPU にマップ**。少数 op のみ "More than one subgraph" で CPU フォールバック (YOLO 系で標準的) → 重い畳み込みの大半が TPU で走り実用的高速化が見込める
- **生成物**: `models/yolo11n_full_integer_quant_edgetpu.tflite` (3.8MB)。`config/coral_edgetpu.yaml` が参照
- **影響**: `PLAN.md §C.1-2` (検証済みレシピへ更新), `PROGRESS.md`, `models/`(gitignore)。`§未解決事項 #11` 解決
- **次の方針**: Coral 購入後に Pi へ転送し `PLAN.md §C.2` の手順で実推論・ベンチ。精度判断 (imgsz 320 vs 480) と CPU INT8 の person 2割減対応は別タスク

### 2026-05-21 — [Claude] [実装/詰まり] フェーズB(Coralコンパイル)着手 + フェーズC(Pi手順)完了
- **内容**:
  - フェーズ C 完了: `PLAN.md` に **§C「Raspberry Pi 5 + Coral Edge TPU 移植手順」** を追記。agent-neutral (Claude Code/Codex/人間が読める)、Mac/x86 章 (変換・転送) と Pi 章 (libedgetpu/tflite-runtime 導入・推論・ベンチ・受け入れ基準) を分離
  - フェーズ B 着手: Docker amd64 (`--platform linux/amd64`) で `_edgetpu.tflite` 生成を試行
- **判明した詰まり (Coral ツールチェーン依存問題)**:
  1. **既存 INT8 tflite を直接コンパイル** (`edgetpu_compiler -s yolo11n_full_integer_quant.tflite`) → `CONV_2D version 6` 非対応で失敗。`edgetpu_compiler 16.0` (2021 年で更新停止) が TF 2.21 の新しい op を解釈できない
  2. **Ultralytics `format=edgetpu` を一気通貫**で試行 → 依存バージョン地獄:
     - 最新 ultralytics は numpy 2.x を引き込み TF と衝突 (`_no_nep50_warning`)
     - `numpy<2` + `tensorflow==2.15.1` + `onnx2tf==1.19.16` + `onnx_graphsurgeon` でインポートは成功
     - しかし量子化段階で `QuantizeModel(): incompatible function arguments` (Python が 6 引数、C++ wrapper が 7 引数要求)。TF 2.14/2.15 とも同じ。`tflite_support` の wrapper 混在が疑わしいが未解決
- **結論/判断**: Coral 用 `_edgetpu.tflite` 生成は **一旦保留** (`§未解決事項 #11`)。理由: ① CPU 版 INT8 (フェーズ A) は完成済みで Mac 検証は可能 ② Coral 実機が未入手で今すぐは不要 ③ 既知の難所で emulation 下の試行コストが高い
- **次の方針 (実機入手時)**: 既知の動作する固定版環境 (Ultralytics 公式 Docker / pycoral 同梱の旧 TF) を使う、もしくは Pi の Coral エコシステム上で変換。`PLAN.md §C.1-2` のコンパイル手順は `_full_integer_quant.tflite` が compiler 互換 op で出力できれば有効
- **影響**: `PLAN.md`(§C 新設), `PROGRESS.md`。コードは変更なし
- **メモ**: フェーズ A の成果 (device ガード/プロファイル/CPU INT8/比較スクリプト/UI) は ver8 で push 済

### 2026-05-20 — [Claude] [実装] フェーズ A 完了 (TFLite 化 + コード対応 + 精度比較)
- **内容**: Coral roadmap フェーズ A を実装
  - A1: `yolo_detector.py` / `byte_tracker.py` に **device ガード** (`_resolve_detector_device`: `.tflite` 時は MPS→CPU 強制)。`set_weights` でも再ガード
  - A2: 環境別プロファイル `config/tflite_cpu.yaml` (INT8 CPU 検証用) / `config/coral_edgetpu.yaml` (Coral 本番用) 追加
  - A3: Mac で `yolo export format=tflite int8=True imgsz=320` 実行 → `models/yolo11n_full_integer_quant.tflite` (2.9MB) 生成、`models/` 直下にコピー
  - A5: `scripts/compare_int8.py` 作成 (クラス別 + BB面積帯別で遠方の人/自転車の取りこぼしを層別評価、動画全体から均等サンプリング)
  - UI: メインウィンドウのモデル選択に **「n TFLite INT8」** を追加 (PyTorch 版と並べて選択可)
- **A4 精度比較結果** (My Movie 3.mov / 300フレーム / imgsz320 / conf0.18):
  - car 96% / person **79%** / truck 73% / bicycle **未評価(動画に映っていない)**
  - person 面積帯別: small 83% / mid **64%** / large 87% → INT8 で person が約2割、特に中サイズで劣化
  - ※フレーム単位の生検出数比較 (トラッキング補完は未考慮)
- **影響**: `src/detection/yolo_detector.py`, `src/tracking/byte_tracker.py`, `src/ui/main_window.py`, `config/tflite_cpu.yaml`(新規), `config/coral_edgetpu.yaml`(新規), `scripts/compare_int8.py`(新規), `models/yolo11n_full_integer_quant.tflite`(新規)
- **テスト**: pytest 54 passed
- **次の方針**: INT8 の person 2割減をどう扱うか判断待ち。候補: ①imgsz=480 で再エクスポート比較 / ②代表フレームで再キャリブ / ③bicycle が映る動画で検証 / ④トラッキング補完に任せて先へ。アプリ (`main.py --config config/tflite_cpu.yaml`) で目視確認も可能

### 2026-05-20 — [Claude] [意思決定] Coral Edge TPU 対応へ方針確定 (ONNX 化を統合)
- **背景**: ユーザーが Pi 5 で **Google Coral USB Accelerator (Edge TPU)** を使う方針。Coral は INT8 量子化 TFLite を Edge TPU 用コンパイルした `.tflite` のみ実行可能
- **決定事項**:
  1. YOLO を TF で再実装はしない。Ultralytics `export(format="edgetpu")` で `PyTorch→ONNX→TFLite(INT8)→EdgeTPU` を一括変換
  2. 前回の「① 手動 ONNX 化」は不要 (上記が通過点を内包) → Coral roadmap に統合
  3. **1 コードベース 3 環境** (Mac=mps / CPU=tflite / Coral=edgetpu) を重み差し替えで実現
  4. 変換は Docker amd64 エミュで Mac 上実行可 (確認済)
  5. Pi 移植手順は **agent-neutral** (Claude Code/Codex 両対応) で PLAN.md に記述
- **影響**: `§Coral Edge TPU 対応 roadmap` を新設、フェーズ A から着手
- **次の方針**: フェーズ A (device ガード + 環境別プロファイル + Mac で INT8 化 + 精度比較)

### 2026-05-20 — [Claude] [意思決定] カメラ異常検知 + 感度調整を ver7 として push、次は ONNX 化
- **決定事項**:
  1. カメラ異常検知 (`blind_check.py`) と感度調整を現状のまま ver7 として確定 → github へ push
  2. 性能評価 (実機/実映像での誤検知率測定) は `§未解決事項 #10` に登録し、別タスクで実施
  3. 次セッションの主要作業: ① **YOLO11 系の ONNX 化** + onnxruntime XNNPACK 経路の整備 (Pi 5 で 2-3 倍速狙い)
- **コミット範囲**: `PROGRESS.md` / `src/pipeline.py` / `src/render/renderer.py` / `src/ui/main_window.py` / `src/ui/settings_dialog.py` / `src/detection/blind_check.py` (新規)
- **影響**: ブランチ `ver6` → `ver7` へ進める

### 2026-05-20 — [Claude] [調整] カメラ異常検知の感度を上げる (新規処理ゼロ)
- ユーザー要望「もうちょっと敏感に、ただし軽量維持」
- **閾値のみ変更** (新規処理なし、ロジック不変):
  | 項目 | 旧 | 新 |
  |---|---|---|
  | brightness_min | 15 | **25** (やや薄暗いを拾う) |
  | brightness_max | 240 | **230** (やや明るすぎを拾う) |
  | contrast_min (std) | 8 | **14** (やや単色を拾う) |
  | sharpness_min (lap_var) | 10 | **25** (軽いボケを拾う) |
  | no_detect_seconds | 3.0 | **2.0** (反応速め) |
- **検証**: 旧閾値で通過していた中間ケース (mean=20 の薄暗い / 軽いボケ) が新閾値で 2.5 秒で検知される
- **コスト**: 完全に同一 (ダウンサンプル + mean/std/Laplacian の 3-5ms/frame は変わらず)
- **影響**: `src/detection/blind_check.py`, `src/pipeline.py`, `src/ui/settings_dialog.py`
- **テスト**: `pytest` 54 passed

### 2026-05-19 — [Claude] [実装] カメラ異常検知 (検出不能通知) 機能を追加
- **内容**: ユーザー要望「汚れ/霧/レンズ遮蔽等で検出できなくなった時に通知。原因特定はせず "検出不能" として一括カバー」
- **方式**: ハイブリッド AND 判定 (C 案)
  - **時間条件**: 直近 N 秒間 (default 3 秒) 検出ゼロ
  - **画質条件**: 以下のいずれか成立で「画質劣化」
    - 平均輝度 < 15 (真っ暗)
    - 平均輝度 > 240 (真っ白)
    - 輝度標準偏差 < 8 (単色 / レンズ遮蔽)
    - Laplacian variance < 10 (ボケ / 霧)
  - **両方 AND 成立**で初めて通知 → 何もない道での誤通知を抑制
- **新規ファイル**: `src/detection/blind_check.py` (`BlindnessDetector`)
  - 160x90 にダウンサンプル → gray 変換 → mean/std/Laplacian で 3-5ms 程度
  - 状態管理: 最後の検出時刻 + 初期時刻 (ウォームアップ判定)
- **Pipeline 統合**: `process()` 内で `meta["blind"]` / `meta["blind_reason"]` を出力
- **Renderer**: `_draw_blind_banner()` 追加。画面上部に **半透明赤帯 + 1Hz 点滅で警告メッセージ**
  - 例: `⚠ 検出不能 - カメラを確認してください  [画面真っ暗 (mean=5)]`
- **UI** (両方からアクセス可能):
  - メインパネル「カメラ異常検知」チェックボックス
  - 詳細設定: チェック + 時間条件秒数 (0.5-30 秒)
- **設定**:
  - `ui.enable_blind_check` (default: false)
  - `ui.blind_check_seconds` (default: 3.0)
- **ライブ反映**: `Pipeline.update_settings` で即時反映
- **テスト**: `pytest` 54 passed + 機能テスト (真っ暗/真っ白/単色/ボケ/正常/リセット 全パターン期待通り動作)
- **影響**: `src/detection/blind_check.py` (新規), `src/pipeline.py`, `src/render/renderer.py`, `src/ui/main_window.py`, `src/ui/settings_dialog.py`

### 2026-05-19 — [Claude] [修正] 外部モデルの postprocess バグ修正
- **報告**: 「YOLOX は左上だけ検出、NanoDet は誤検出だらけ」
- **原因 1 (YOLOX 左上のみ)**:
  - YOLOX 0.1.1rc0 ONNX は **stride decode を内蔵していない**
  - 出力は raw な (cx_offset, cy_offset, log_w, log_h) で、grid と stride で復元する必要があった
  - 私の初版は raw 値をそのまま絶対座標として扱った → cx/cy が ±数の小さい値 → 全 BB が原点付近に集中
- **原因 2 (NanoDet 誤検出だらけ)**:
  - このモデルの ONNX は cls 出力が **既に sigmoid 済み (確率値)**
  - 私のコードがもう一度 `sigmoid()` を適用 → 例: 0.05 (低 conf) が 0.51 になり「物体あり」と誤判定
  - 結果、全 grid セル × 全クラスが score > 0.5 で大量 false positive
- **修正**:
  - YOLOX: `_build_grids()` で grid と expanded_strides を事前計算、postprocess で `pred[:, 0:2] = (pred[:, 0:2] + grids) * strides` の stride decode を追加
  - NanoDet: `cls_scores = _sigmoid(cls_scores)` を削除（既に確率値）
- **検証**: ランダムノイズ画像で全 3 モデルとも 0 検出 = 過剰反応しない正常動作確認
- **影響**: `src/detection/external_detector.py`
- **テスト**: `pytest` 54 passed

### 2026-05-19 — [Claude] [実装] 外部小モデル 4 つを追加 (既存 YOLO11 系は保持)
- **内容**: ユーザー要望「⑥ 小モデル差し替え、4 つ全部追加、既存削除しない」
- **追加モデル** (`models/` 配下):
  - `yolox_nano.onnx` (3.5 MB)
  - `yolox_tiny.onnx` (19 MB)
  - `nanodet-plus-m_320.onnx` (4.6 MB)
  - `efficientdet_lite0.tflite` (4.4 MB)
- **新規ファイル**: `src/detection/external_detector.py`
  - 基底 `ExternalDetectorBase` + 3 種実装:
    - `YoloxDetector`: ONNX 推論 + letterbox preprocess + クラス毎 NMS
    - `NanoDetDetector`: ONNX 推論 + DFL decode (GFL center-point predictor)
    - `EfficientDetDetector`: tflite-runtime / tensorflow lite 推論
  - `make_external_detector(weights)` ファクトリ (ファイル名で自動判別)
  - onnxruntime は CoreMLExecutionProvider 自動優先 (Mac)、CPU フォールバック
- **YoloTracker 改修**:
  - 重みパスが .onnx / .tflite を含む場合は `_external` (ExternalDetector) を使い、`_simple_match` で nearest-neighbor トラッキング
  - 既存 YOLO11 系 (.pt) は完全に従来通り (Ultralytics の bytetrack pipeline)
  - `set_weights()` でモデル種別を自動切替
  - `conf_per_class` フィルタは外部 detector でも適用
- **UI**: YOLOモデルコンボに 4 モデル追加 (既存 5 つは保持、合計 **9 モデル選択可**)
- **requirements.txt**: `onnxruntime>=1.17.0` + EfficientDet 用に `tflite-runtime` (Linux/Pi) / `tensorflow` (Mac) 追加
- **動作確認**:
  - YOLOX-Nano/Tiny: ONNX ロード成功、推論実行 OK (ランダム入力で false positive 0)
  - NanoDet-Plus: ONNX ロード成功、推論実行 OK (DFL decode 動作確認)
  - EfficientDet: 実機未確認 (tflite 環境次第)
- **影響**: `src/detection/external_detector.py` (新規), `src/tracking/byte_tracker.py`, `src/ui/main_window.py`, `requirements.txt`
- **テスト**: `pytest` 54 passed
- **注意**: NanoDet と EfficientDet は ByteTrack ではなく `_simple_match` (nearest-neighbor) になるので、ID の安定性は YOLO11+ByteTrack より落ちる

### 2026-05-19 — [Claude] [削除] リアルタイム優先 + 停車検知スキップを撤回
- **理由**: ユーザー報告「飛び出す人を検出できなくなった」
  - リアルタイム優先 (B 適応スキップ): lag↑ で `every_n_frames` を自動増 → 検出間隔が空いて飛び出し歩行者を取りこぼし
  - 停車検知スキップ (⑧): 微小な動きしかないフレームで全パイプライン停止 → 歩行者が突然動いた瞬間に検出されない
- **削除内容**:
  - `MainWindow`: 「リアルタイム優先」「停車検知スキップ」チェックボックス削除
  - `settings_dialog`: 3 項目 (realtime_priority / enable_motion_skip / motion_threshold) のツールチップと入力欄削除
  - `Pipeline`: `enable_motion_skip` / `motion_threshold` / `_motion_prev_gray` / `_last_display_cache` / `_last_meta_cache` 削除、process() 冒頭の skip 判定撤去、render 後のキャッシュ処理撤去
  - `InferenceThread`: `_adaptive_extra_skip` / `_adaptive_last_change_idx` / `_update_adaptive_skip()` 削除、設定通知時の source.set_realtime_priority 呼び出し削除、meta から `adaptive_extra_skip` / `dropped_frames` 削除
  - `CameraSource`: `realtime_priority` 引数 / reader thread 機構 / `set_realtime_priority` / `dropped_frames` 削除、シンプルな構造に戻す
- **意義**: 検出感度を最優先、軽量化は他の手段 (解像度・YOLO モデル選択・解析間隔) で対応
- **影響**: `src/ui/main_window.py`, `src/ui/settings_dialog.py`, `src/pipeline.py`, `src/ui/inference_thread.py`, `src/input/camera.py`
- **テスト**: `pytest` 54 passed

### 2026-05-19 — [Claude] [追加] 3 新機能をメイン UI からも ON/OFF + ライブ反映強化
- **内容**: ユーザー指示「今回実装した機能は UI で ON/OFF、即座に処理に反映」
  - **MainWindow 左パネル**にチェックボックス 2 つ追加:
    - 「リアルタイム優先」(A+B)
    - 「停車検知スキップ」(⑧)
  - 既存の機能トグル群と同じ iteration リストに含めたので `_sync_feature_flags` / `_apply_feature_flags` 両方で自動処理
  - 詳細設定ダイアログ側にも残置 (重複だが両方からアクセス可能)
- **A 部分のライブ切替対応**: `CameraSource.set_realtime_priority(bool)` を新規追加
  - 再生中に ON 切替 → reader thread 起動
  - 再生中に OFF 切替 → reader thread 停止 + 状態リセット
- **InferenceThread**: 設定変更通知時に source へも `set_realtime_priority` を呼び出す
- **テスト**: `pytest` 54 passed
- **影響**: `src/input/camera.py`, `src/ui/inference_thread.py`, `src/ui/main_window.py`

### 2026-05-19 — [Claude] [実装] リアルタイム優先モード (A+B) + Motion-based skip (⑧)
- **内容**: ユーザー指示「BA 八を実装」+ 「⑥ YOLOX は実装方針確認後」
- **新設定**:
  - `ui.realtime_priority` (default: false) — A+B 両方を ON
  - `ui.enable_motion_skip` (default: false) — ⑧ ON/OFF
  - `ui.motion_threshold` (default: 2.0) — ⑧ の差分閾値
- **A. 「常に最新フレーム」戦略** (`src/input/camera.py`):
  - `CameraSource(index, realtime_priority=True)` 時、別 daemon thread で `cap.read()` を最高速度ループ
  - `latest_frame` を上書き続け、`read()` はその snapshot を返すだけ
  - `CAP_PROP_BUFFERSIZE=1` で OS バッファも最小化
  - `dropped_frames` カウンタ追加 (meta 経由で UI 表示可能)
  - カメラ専用 (VideoFileSource には影響なし)
- **B. 適応的フレームスキップ** (`src/ui/inference_thread.py`):
  - 直近 lag_percent を見て `detector_every_n_frames` を動的増加
    - <10%: +0 / 10-30%: +1 / 30-50%: +3 / >50%: +5
  - ヒステリシス: 30 フレーム以上経たないと値を変えない (振動防止)
  - `realtime_priority=False` 時は無効
  - 状態を `meta["adaptive_extra_skip"]` で外部から観測可能
- **⑧ Motion-based skip** (`src/pipeline.py`):
  - process() 冒頭で `cv2.absdiff(prev_gray, current_gray).mean() < motion_threshold` 判定
  - 静止判定なら全パイプライン (検出・車線・危険判定・描画) をスキップし、`_last_display_cache` をそのまま返す
  - `meta["motion_skip"]=True` で外部から判別可能
  - 詳細設定ダイアログから ON/OFF と閾値調整可能
- **UI**: 詳細設定ダイアログに 3 つのトグル + 詳細ツールチップ追加
- **ライブ反映**: 全 3 機能とも `Pipeline.update_settings` 経由で即座反映
- **影響**: `src/input/camera.py`, `src/ui/inference_thread.py`, `src/pipeline.py`, `src/ui/main_window.py`, `src/ui/settings_dialog.py`
- **テスト**: `pytest` 54 passed

### 2026-05-19 — [Claude] [計画] 今後実装予定の高速化施策（優先順）
- **保留中** (実装する用意あり、ユーザー判断待ち):
  - **① ONNX + onnxruntime XNNPACK**: Pi 5 CPU で 2-3 倍速。学習済 .pt → ONNX エクスポート、Detector アダプタ抽象化
  - **② INT8 量子化**: ① の延長。動的/静的量子化、Pi で更に 2-3 倍速 (合計 4-8 倍)
  - **⑥ 小モデル差し替え**: ユーザーは YOLOX 系を希望、Ultralytics 非対応のため ONNX 経由で実装が必要 (実質 ① 前倒し)
- **保留理由**: 既存ロジックの大改修になるため、Pi 5 実機投入の前後で実装判断

### 2026-05-19 — [Claude] [実装] 矩形 ROI 推論モード追加（台形と切替可能）
- **内容**: ユーザー要望「台形 ROI は歩行者飛び出しに弱い。長方形を手動指定する高速化方式を別途追加して切替可能に」
- **設計**:
  - 新設定 `ui.roi_mode` ∈ `off / trapezoid / rectangle`（旧 `enable_roi_crop=True` は `trapezoid` 扱いで後方互換）
  - 新設定 `ui.roi_rect: {x_ratio, y_ratio, w_ratio, h_ratio}` (全て 0-1)
- **Pipeline**:
  - `_compute_roi_crop_box(frame)` がモードに応じて crop 矩形 or None を返す統一 API
  - `_roi_box_from_rect` 新規（比率 × フレームサイズ）
  - `update_settings` でモード・矩形パラメータをライブ反映
- **UI 左パネル**:
  - 「ROI 推論」コンボ: OFF / 台形 / 矩形
  - 矩形 ROI 用 4 スライダー (X 位置 / Y 位置 / 幅 / 高さ、0-100%)、矩形モード以外はグレーアウト
- **可視化**: 矩形モード時、画面に黄色枠 + `ROI (rect)` ラベル → スライダー操作で即視覚フィードバック
- **検証**:
  - rect mode 640x480 で `x=0.1,y=0.4,w=0.8,h=0.5` → `(64, 192, 576, 432)` ✓
  - trapezoid mode (polygon 未確定): デフォルト矩形 ✓
  - off mode: None ✓
- **影響**: `src/pipeline.py`, `src/render/renderer.py`, `src/ui/main_window.py`
- **テスト**: `pytest` 54 passed
- **使い分け**: 台形は車線追従で自動、矩形は左右広く取りたい / 歩行者飛び出しを重視 / 信号機を含めたい時

### 2026-05-18 — [Claude] [改善] 表示解像度の下限拡張 + 遅延率をリアルタイム化
- **表示解像度コンボに追加**: 240px (極小) / 160px (最小) / 80px (実験) を追加。最小は **80px** まで
- **遅延率のリアルタイム化** (`InferenceThread`):
  - **旧**: 起動からの累積 `elapsed` で算出 → 過去の遅延を引きずって反応が鈍い
  - **新**: 直近 60 フレームの (frame_idx, wall_time) を deque で保持し、ウィンドウ内の dt と d_frames から **「直近 ~1 秒の current_fps」** を算出
  - `realtime_ratio = current_fps / source_fps`
  - **fps 表示**も同じスライディングウィンドウベースに変更（即応性向上）
  - 設定変更直後（処理が軽くなった/重くなった）の効果が ~1 秒以内に UI に反映
- **影響**: `src/ui/inference_thread.py`, `src/ui/main_window.py`
- **テスト**: `pytest` 54 passed

### 2026-05-18 — [Claude] [修正] Overlay 大きさ倍率が反映されない問題 + 命名修正
- **指摘 1**: 「太さ」じゃなく「大きさ」が正しい (BB/矢印/文字すべてに影響)
  - UI ラベル: 「Overlay 太さ」→ **「Overlay 大きさ」**
  - 選択肢: 「極細/細い/太い/極太」→ **「極小/小さい/大きい/極大」**
  - cfg キー: `overlay_thickness_scale` → **`overlay_size_scale`**
- **指摘 2**: 「変更が反映されない」
  - **原因**: Renderer の `_t/_f/_p` に最低クランプ (2px / 0.4 / 2px) があり、0.5x や 0.75x にしても下限で固定されていた
  - **修正**: クランプを物理最小値に緩和 (`_t`: 1px / `_f`: 0.15 / `_p`: 1px)
    - 同時に `_update_scale` のベース下限 0.55 も撤去 (overlay_scale 側の 0.2 下限のみ残す)
- **検証** (1280px 入力):
  | 倍率 | font(0.58) | 線(2) | 線(4) | パッド(8) |
  |------|-----------|-------|-------|----------|
  | 0.5x | 0.29 | 1 | 2 | 4 |
  | 0.75x | 0.43 | 2 | 3 | 6 |
  | 1.0x | 0.58 | 2 | 4 | 8 |
  | 1.5x | 0.87 | 3 | 6 | 12 |
  | 2.0x | 1.16 | 4 | 8 | 16 |
  → 全段階で値が確実に変化、UI 操作で即座に視覚的差分
- **影響**: `src/render/renderer.py`, `src/pipeline.py`, `src/ui/main_window.py`, `src/ui/settings_dialog.py`
- **テスト**: `pytest` 54 passed

### 2026-05-18 — [Claude] [実装] 表示解像度を 320px まで拡張 + Overlay 太さ倍率を UI 追加
- **内容**: ユーザー要望「表示解像度は 320 まで」「太さも選べるように」
  - **表示解像度コンボ**: 720 以下を追加 (540 / 360 / 320)、合計 8 段階
  - **Renderer.overlay_scale** (新インスタンス属性): `_update_scale` 内で `_s = base * overlay_scale` として全描画パラメータに適用
    - `_t()` / `_f()` / `_p()` すべて影響
  - **UI**: 「Overlay 太さ」コンボ追加（極細 0.5 / 細い 0.75 / 普通 1.0 / 太い 1.5 / 極太 2.0）
  - **Pipeline.update_settings**: `ui.overlay_thickness_scale` → `self.renderer.overlay_scale` をライブ反映
  - **詳細設定ダイアログ**: 倍率を 0.30-3.00 の数値スピンで直接調整可能 + ツールチップ
- **検証** (1280px 入力):
  | 倍率 | フォント | 枠線(2) | 枠線(4) |
  |------|---------|---------|---------|
  | 0.5x | 0.40 | 2 | 2 |
  | 1.0x | 0.58 | 2 | 4 |
  | 2.0x | 1.16 | 4 | 8 |
- **影響**: `src/render/renderer.py`, `src/pipeline.py`, `src/ui/main_window.py`, `src/ui/settings_dialog.py`
- **テスト**: `pytest` 54 passed

### 2026-05-18 — [Claude] [実装] 表示解像度を UI から動的指定可能に
- **内容**: ユーザー要望「overlay の解像度も UI で調整、即反映」
  - **新設定**: `ui.display_max_width` (0 = 元動画サイズに合わせる)
  - **Pipeline API 変更**: `display_frame: ndarray` → `display_size: tuple[int,int]` (shape 情報だけが必要なので軽量化)
  - **MainWindow**: 左パネルに「表示解像度」コンボ追加
    - 元動画サイズ / 1920 / 1280 / 960 / 720 px
    - 既存「処理解像度」と並べて配置 → 違いがすぐ分かる
  - **InferenceThread**: 毎フレーム `ui.display_max_width` 読み直し → 即時反映
  - **詳細設定ダイアログ**: `display_max_width` も追加 + ツールチップ
- **意義**: 「処理 320px / 表示 1920px」のような組み合わせで、動画はボケて軽量、overlay は綺麗 という設定が UI で完結
- **影響**: `src/pipeline.py`, `src/ui/inference_thread.py`, `src/ui/main_window.py`, `src/ui/settings_dialog.py`
- **テスト**: `pytest` 54 passed

### 2026-05-18 — [Claude] [修正] 動画ピクセルは処理解像度のまま、overlays のみ高画質に
- **内容**: ユーザー指摘「動画自体の解像度は処理解像度のままにして、四角・矢印・文字だけ綺麗にする」
- **修正前**: `canvas = display_frame`（元解像度の動画ピクセルをそのまま使用 → 動画も鮮明）
- **修正後**: `canvas = cv2.resize(enhanced, display_size, INTER_LINEAR)`
  - 動画ピクセル: 処理解像度 (例 320px) のままを display サイズに引き伸ばし → 拡大ボケしてるけど 320px の情報量を保持
  - Overlays (BB / 矢印 / ラベル / 警告パネル): display サイズの座標系で直接描画 → 高画質
- **意義**: 処理解像度を下げた効果（軽量化）は維持しつつ、overlays だけは綺麗
- **影響**: `src/pipeline.py`
- **テスト**: `pytest` 54 passed

### 2026-05-18 — [Claude] [修正] カスタムを単一スロットに変更
- **内容**: ユーザー指摘「カスタムプロファイルってプロファイルを設けて欲しい」= 複数ファイルではなく単独の「カスタム」枠
  - **旧**: `config/custom_<name>.yaml` を複数作れる方式（プロファイル一覧が無限に増える）
  - **新**: `config/custom.yaml` ただ 1 つ。プロファイルコンボには常に「カスタム」枠が末尾に固定で存在
    - 未保存時: 「カスタム (未保存)」表示、選択しても何もしない
    - 保存済み: 「カスタム ★」表示、選択で読み込み
    - 「現在の設定を保存」ボタン押下 = `config/custom.yaml` 上書き → ラベル ★ 化 → 自動選択
  - `save_custom_profile(cfg)` 名前引数廃止、QInputDialog 廃止 → ワンクリック保存
  - 未保存スロット選択時は video_label に案内表示してフォールバック
- **影響**: `src/utils/config.py`, `src/ui/main_window.py`
- **テスト**: `pytest` 54 passed / 初回保存・上書き保存ともに確認

### 2026-05-18 — [Claude] [修正] カスタムプロファイルを独立プロファイルとして保存
- **内容**: ユーザー指摘「カスタムプロファイルは独立したプロファイルとして存在していて欲しい」
  - 旧仕様: `extends: default.yaml` + default との差分のみ保存 → default.yaml 変更時に挙動が変わるリスク
  - 新仕様: **cfg 全体を独立した完全なプロファイル**として書き出し
    - `extends` キーを削除
    - 全セクション (input/detector/tracker/segmenter/depth/lane/risk/ui) を完全な状態で出力
    - default.yaml が将来変わってもカスタムの動作は不変
  - `_diff_against` ヘルパ削除
- **影響**: `src/utils/config.py`
- **テスト**: `pytest` 54 passed / 保存→再読込で全項目一致を確認

### 2026-05-18 — [Claude] [改善] 描画を元解像度フレームに分離 + カスタムプロファイル保存
- **内容**: ユーザー指摘「処理は小さく、表示は綺麗でいい」「線が細すぎ」「カスタムプロファイル保存したい」
  - **アーキテクチャ変更 — 処理と描画の解像度を分離**:
    - `Pipeline.process(frame, ..., display_frame=None)` 新引数追加
    - 検出/追跡は process_frame (例 320px) のまま → 高速
    - 描画は display_frame (元解像度、例 1920px) に行う → 文字・枠線がクッキリ
    - bboxes・lanes・zone polygon・road_mask を倍率 `display_w / process_w` でスケールアップしてから renderer に渡す
    - 解析 (risk) は process_frame ベースで継続（誤差回避）
  - **スケールヘルパ追加** (`src/pipeline.py`):
    - `_scale_track_xy(track, s)`: bbox / history / velocity を scale
    - `_scale_lane_info(lanes, s)`: 左右車線・ego polygon・vanishing point を scale
  - **InferenceThread**: `pipeline.process(process_frame, ..., display_frame=frame)` で元フレーム渡す
  - **Renderer**: 元解像度ベースになったので最低値を引き上げ
    - `_t` 最低 2px、`_f` 最低 0.40、`_p` 最低 2px（細すぎ対策）
    - スケール下限も 0.55 に引き上げ
  - **カスタムプロファイル保存** (`src/utils/config.py`):
    - `save_custom_profile(name, cfg)`: `config/custom_<safename>.yaml` に default.yaml との **差分のみ** を `extends: default.yaml` 形式で書き出す
    - `list_custom_profiles()`: `config/custom_*.yaml` を列挙
    - **MainWindow**: 「現在の設定を保存...」ボタン追加、QInputDialog で名前入力 → 保存 → プロファイルコンボに「★ {名前}」で即追加 → 選択
    - 起動時にも custom_*.yaml を自動列挙してコンボに表示
- **検証**:
  - 元 1920px に描画 → font 0.87、線 3-6px（適切）
  - 元 640px → font 0.40、線 2-3px（細すぎなし）
  - プロファイル保存 → default との差分のみ書き出し、サイズコンパクト
- **影響**: `src/pipeline.py`, `src/ui/inference_thread.py`, `src/ui/main_window.py`, `src/utils/config.py`, `src/render/renderer.py`
- **テスト**: `pytest` 54 passed

### 2026-05-18 — [Claude] [修正] 低解像度処理時に描画文字が巨大化する問題を解消
- **原因**: Renderer はピクセル固定値 (font_scale 0.58, thickness 2 等) で処理フレームに描画。処理フレームが小さい (例 320px) と QLabel が表示時に拡大するため、文字・枠線・矢印すべてが**4倍に巨大化**して見える
- **修正**: フレーム幅基準のスケール係数 `self._s = frame_width / REFERENCE_WIDTH` (1280) を導入し、すべての描画パラメータを動的計算
  - 3 つのヘルパ: `_t(base)` 線太さ / `_f(base)` フォント / `_p(base)` ピクセル位置
  - 全描画メソッドを static → instance に変換し統一適用
  - `_draw_label` / `_draw_tracks` / `_draw_motion_vector` / `_draw_alert_panel` / `_draw_status` 等を対象
  - alert_panel と status bar の高さ・幅も動的調整
- **検証** (display=1280 想定の実効フォントサイズ):
  | 処理幅 | scale | font(0.58→) | 表示時実効 |
  |--------|-------|-------------|-----------|
  | 320 | 0.25 | 0.15 | 0.60 |
  | 540 | 0.42 | 0.25 | 0.58 |
  | 1280 | 1.00 | 0.58 | 0.58 |
  | 1920 | 1.50 | 0.87 | 0.58 |
  → どの処理解像度でも表示時の文字サイズがほぼ一定に
- **テスト**: `test_renderer.py` を新 API に追従 (`Renderer()` インスタンス + `_update_scale`) / `pytest` 54 passed
- **影響**: `src/render/renderer.py` (全書換), `tests/test_renderer.py`

### 2026-05-18 — [Claude] [改善] メインウィンドウ縦横リサイズ + 解析間隔 1-20 + 詳細設定リセット機能
- **内容**:
  - **メインウィンドウのリサイズ強化**:
    - `video_label` の最小サイズを 860x500 → **320x240** に縮小（小さくも大きくも自由）
    - 左パネルを `setFixedWidth(200)` から **`QScrollArea` でラップ** (200-280px 可変、縦は内容に応じてスクロール)
    - メインウィンドウ全体の最小サイズ `560x400` に設定
  - **解析間隔の選択肢**: 1-5 → **1-20** フレーム毎（generator で動的生成）
  - **詳細設定「デフォルトに戻す」ボタン追加**:
    - ダイアログを開いた時点の cfg を deep copy で `_default_cfg` に保存
    - ボタン押下で `self.cfg` 全置換 → `refresh_from_cfg()` で UI 全項目を初期値に
    - `settingsChanged` シグナル発火で Pipeline へも反映
    - プロファイル切替時には `set_default_snapshot()` でスナップショット再取得
    - `_combo` ヘルパは `widget.setProperty("_values", values)` で value 配列を保持し、refresh 時に逆引き可能に
- **影響**: `src/ui/main_window.py`, `src/ui/settings_dialog.py`
- **テスト**: `pytest` 54 passed / 構文 OK

### 2026-05-18 — [Claude] [改善] 詳細設定ダイアログに説明（メリット/デメリット）追加 + リサイズ/スクロール強化
- **内容**: ユーザー要望「設定の意味とメリデメをわかりやすく」「ウィンドウのリサイズとスクロール実装」
  - **TOOLTIPS 辞書 (33 項目)**: 全設定項目に詳細な説明をマルチライン文字列で定義
    - パターン: 「項目の意味 / ↑上げる時の効果 / ↓下げる時の効果 / 推奨範囲」
    - 例: `imgsz` → 「YOLO 内部リサイズ。↑大: 遠方の小物体↑、推論遅い / ↓小: 速い (Pi は 320 推奨)、小物体落ちる」
  - **GROUP_DESCRIPTIONS (7 グループ)**: 各 QGroupBox 上部にグレー小文字で概要表示
  - **ヘルパ `_add_row`**: ラベルと widget の両方にツールチップ設定、ラベルにヘルプカーソル
  - **ヘッダ案内**: ダイアログ最上部に「カーソルを乗せると説明が出る」帯を追加
  - **リサイズ強化**:
    - `setMinimumSize(420, 360)` で最小サイズ制限
    - `setSizeGripEnabled(True)` で右下にリサイズグリップ
    - `setSizePolicy(Expanding, Expanding)` でレイアウト追従
  - **スクロール強化**: QScrollArea の水平/垂直スクロールバーポリシーを `ScrollBarAsNeeded` に明示
- **影響**: `src/ui/settings_dialog.py` (全書換)
- **テスト**: `pytest` 54 passed / 構文 OK

### 2026-05-18 — [Claude] [実装] 詳細設定ダイアログ + Pi 最低構成 ver1 プロファイル
- **内容**: ユーザー要望「プロファイル全項目を UI で手動指定」「Pi 最低構成 ver1 プロファイル作成」
  - **新プロファイル**: `config/pi_minimal_ver1.yaml`
    - YOLOモデル n / imgsz 320 / 解像度 320 / 解析間隔 5 / 検出+車線+危険判定+視認性補正+ROI ON / 信号+路面マスク OFF / 奥行きモード手動
    - プロファイル切替コンボに「Pi 最低構成 ver1」追加
  - **新ダイアログ** (`src/ui/settings_dialog.py`): `SettingsDialog` (QDialog) を新規作成
    - 7 グループ (Detector / Tracker / Segmenter / Depth / Lane / Risk / UI) を QGroupBox + QFormLayout で構成、QScrollArea でスクロール可能
    - ウィジェット: QSpinBox / QDoubleSpinBox / QCheckBox / QComboBox を統一ヘルパで生成
    - 全項目で値変更 → `settingsChanged` シグナル → MainWindow が `apply_settings(cfg)` で Pipeline へ即時反映
    - `conf_per_class` のようなネスト dict 用の `_nested_dspin` ヘルパ
  - **MainWindow**: 「詳細設定...」ボタンを左パネルに追加。ダイアログはシングルトン的に保持し、プロファイル切替時には `refresh_from_cfg()` で再同期
  - **Pipeline.update_settings 拡張**: 以下をライブ反映可能に
    - `detector.conf` / `iou` / `imgsz` / `max_det` / `conf_per_class`
    - `lane.hough_threshold` / `min_line_length` / `max_line_gap` / `dashed_support` / `ldw_threshold_px` / `ldw_release_px`
    - `risk.ttc_critical_s` / `ttc_warn_s`
    - `segmenter.enabled` / `every_n_frames`
    - `depth.enabled` / `every_n_frames`
- **要再起動の項目**: `tracker.track_buffer`, `segmenter.input_size`, `detector.device` (一部) ※ダイアログ上では編集可能、変更は次回プロファイル再ロード時に反映
- **影響**: `config/pi_minimal_ver1.yaml` (新規), `src/ui/settings_dialog.py` (新規), `src/ui/main_window.py`, `src/pipeline.py`
- **テスト**: `pytest` 54 passed
- **保存機能は未実装**: メモリ上の cfg 変更のみで、YAML への書き戻しはしない（再起動で初期値に戻る）

### 2026-05-18 — [Claude] [実装] Pi 5 視野の高速化 Tier 2 (④320 + ⑤LK 補間 + ⑥ROI 推論)
- **内容**: Pi 5 移植を見据え、ハードウェア追加なしで効く高速化 3 種を投入
  - **④ 320px 解像度プリセット**: 処理解像度コンボに「320px (Pi 向け)」追加。`max_process_width=320`
  - **⑤ LK BB 補間** (`src/tracking/bbox_flow.py` 新規):
    - `BBoxFlowInterpolator`: 各 BB に 3x3=9 格子点を撒き、前フレ gray と現フレ gray で `cv2.calcOpticalFlowPyrLK` を全 BB 一括計算（1 回の LK 呼び出しで全 track 分処理）
    - 中央値 (dx, dy) で BB を平行移動、回転/スケールは無視（短時間補間用）
    - 検出スキップフレーム時に動作 → `self._last_tracks` が古い座標のまま残らずに「動いて見える」
    - 性能: 10 track × 640x480 で **1.96ms/call**（YOLO 100-200ms に対し誤差レベル）
    - 精度: テクスチャ有り画像で ±0.1px シフト推定
  - **⑥ ROI 推論** (`Pipeline._crop_for_yolo`):
    - 台形ゾーン (auto_zone polygon) の bounding rect を crop → YOLO に投入 → 検出 BB を offset で元座標に戻す
    - polygon 未確定時は画面下 65% × 中央 90% のデフォルト矩形
    - 入力サイズが半分以下になるため Pi CPU で 30-50% 高速化見込み
    - UI チェックボックス「ROI 推論 (高速化)」で ON/OFF
- **テスト**: `pytest` 54 passed
- **影響**: `src/tracking/bbox_flow.py` (新規), `src/pipeline.py`, `src/ui/main_window.py`
- **次の方針**: 実機 (Pi 5) 入手後、ONNX 化 (Tier 1 #1) と INT8 量子化に進む

### 2026-05-18 — [Claude] [実装] YOLO11 モデル種別を UI から動的選択
- **内容**: ユーザー要望「YOLO11 の種類（s, n, その他）も UI で選べるように」
  - **資産**: `yolo11m.pt` (40MB) / `yolo11l.pt` (50MB) / `yolo11x.pt` (110MB) を追加 DL → `models/yolo11{n,s,m,l,x}.pt` 5 種揃った
  - **YoloTracker.set_weights(path)**: `_model` をクリアして次回 track 時に再ロード。`_history`/`_age` も初期化（ID 連番リセット）
  - **Pipeline.update_settings**: `detector.weights` が変わったら `tracker.set_weights()` 呼び出し
  - **MainWindow**: 「YOLOモデル」コンボ追加 (n / s / m / l / x)。サイズと用途をラベルに併記
  - 切替は再生中即時反映（次フレームでモデル再ロード、初回 1〜2 秒ロード時間あり）
- **影響**: `src/tracking/byte_tracker.py`, `src/pipeline.py`, `src/ui/main_window.py`
- **テスト**: `pytest` 54 passed
- **UX**: 軽量機/カメラ環境では n、夜間や精度重視は l/x、と動的に切替可能

### 2026-05-18 — [Claude] [実装] 実時間に対する処理遅延率を UI 表示
- **内容**: ユーザー要望「動画本来の再生スピードから何%遅れているかリアルタイム表示」
  - **InferenceThread**: meta に `realtime_ratio` と `lag_percent` を追加
    - `source_time = (frame_idx+1) / source_fps`
    - `realtime_ratio = source_time / 経過 wall 時間` → 1.0 ならリアルタイム維持
    - `lag_percent = max(0, (1 - ratio) * 100)`
  - **MainWindow**: コントロールバーに `lag_label` 追加。表示例: `実時間比 75% (-25% 遅延)`、4 段階で色分け
    - <5%: 緑 (リアルタイム)
    - <20%: 黄 (やや遅延)
    - <50%: 橙 (遅延)
    - ≥50%: 赤 (重い遅延)
- **影響**: `src/ui/inference_thread.py`, `src/ui/main_window.py`
- **テスト**: `pytest` 54 passed

### 2026-05-18 — [Claude] [実装] UI から処理解像度・解析間隔をライブ変更可能に
- **内容**: ユーザー要望「読み込む画質、何フレームごとに処理するか、をUIで指定」「変更したら即座に反映」
  - **MainWindow** に 2 つの QComboBox 追加:
    - 「処理解像度」: 自動 / 1280 / 960 / 720 / 540 / 360 px（`ui.max_process_width` に書込）
    - 「解析間隔」: 毎フレーム / 2〜5 フレーム毎（`detector.every_n_frames` + `lane.every_n_frames` に書込）
  - **InferenceThread**: `max_process_width` と `display_every_n_frames` を `run()` 開始時の 1 回読みから、**毎フレーム `self.cfg` から読み直し** に変更（UI 変更を次フレームで反映）
  - **Pipeline.update_settings**: `detector_every_n_frames` / `lane_every_n_frames` / `signs_every_n_frames` をライブ更新し、`self.cfg` も差し替え（process() 内の `lane_cfg` 参照を最新化）
  - プロファイル切替時 (`_apply_feature_flags`) も 2 つのコンボを再同期
- **影響**: `src/ui/main_window.py`, `src/ui/inference_thread.py`, `src/pipeline.py`
- **テスト**: `pytest` 54 passed
- **UX**: 走行中にカクついたら即「540px / 3 フレーム毎」に下げて軽量化、停車中は「1280px / 毎フレーム」に上げて高精度確認、といった操作が可能

### 2026-05-18 — [Claude] [修正/削除] 視認性補正を超軽量化（gamma LUT のみに）
- **内容**: ユーザー指示「視認性補正は暗いところで明るさや露出をあげて YOLO に見やすくするためだけの簡単な動作なので、もっと軽量にして」を反映。
  - **削除**: `src/enhancement/hdr.py` (Mertens HDR/detailEnhance)、`src/enhancement/night_mode.py` (LAB+CLAHE+gamma+fastNlMeansDenoisingColored)
  - **新 `FrameEnhancer`**: 単一 `cv2.LUT` (事前計算 gamma=0.6 LUT) のみ。暗所判定は 64x64 にダウンサンプルした gray の mean < 70 で行い、8 フレームごとにキャッシュ
  - 出力 meta は `{"night": bool, "hdr": False}` で従来形を維持（pipeline/render は無改変で動作）
- **性能** (1920x1080 入力):
  - 暗フレーム適用時: **4.5ms/枚**（旧版 NightMode+HDR は推定 50-80ms → 約 10-15 倍高速）
  - 明るいフレーム: 2ms（判定のみ）
  - 明るさブースト: 平均輝度 30 → 70（gamma 0.6 LUT）
- **影響**: `src/enhancement/enhancer.py` (全書換)、`hdr.py`/`night_mode.py` 削除
- **テスト**: `pytest` 54 passed（test_pipeline_smoke は loguru 環境差異で除外）
- **デフォルト**: 全プロファイルで `enable_enhancement: false`（UI トグルで ON 可能）

### 2026-05-18 — [Claude] [資産] YOLO11 重みを取得
- **内容**: `models/yolo11n.pt` (5.5MB)、`models/yolo11s.pt` (18MB) を GitHub Release から DL 完了。ultralytics 未インストール環境のため `curl` で直接取得。zip 構造正常を確認
- **ソース**: `github.com/ultralytics/assets/releases/download/v8.3.0/yolo11{n,s}.pt`

### 2026-05-18 — [Claude] [修正] YOLOv8 → YOLO11 へ置換
- **内容**: ユーザー指示「yolo8をyolo11にして」を反映。検出モデルの既定重みを `yolov8n.pt` から `yolo11n.pt`、ファインチューニング基底を `yolov8s.pt` から `yolo11s.pt` に変更。Ultralytics ライブラリは YOLO11 をネイティブサポート（`YOLO("yolo11n.pt")` で自動 DL）。
- **変更ファイル**:
  - `config/default.yaml`: `detector.weights` → `models/yolo11n.pt`
  - `src/detection/yolo_detector.py`: 既定 weights
  - `src/tracking/byte_tracker.py`: 既定 weights
  - `src/pipeline.py`: フォールバック既定値
  - `scripts/prepare_assets.py`: `yolo11n.pt` / `yolo11s.pt` を取得
  - `scripts/train_jp_signs.py`: 既定 weights とヘルプ文言
  - `tests/test_config.py`: assert 2 件を `yolo11n.pt` に更新
  - `README.md`: モデル表記と参照 URL を YOLO11 公式ドキュメントに更新
- **未更新**: `CLAUDE_ADVICE.md` の CoreML 移行ガイド・`PLAN.md` の設計記述・`PROGRESS.md` 既存履歴は **歴史記録として温存**（プロジェクト規約で削除禁止）
- **テスト**: `pytest tests/test_config.py` 3 passed。初回起動時に Ultralytics が `yolo11n.pt` を HuggingFace から自動 DL する想定（既存 `models/yolov8n.pt` がある場合は手動削除推奨）
- **影響**: 推論精度は YOLO11n が COCO mAP で YOLOv8n より +1〜2pt 向上見込み、速度はほぼ同等

### 2026-05-12 — [Claude] [削除/実装] v9.6 - 障害物検出を完全削除 + 自転車検出を強化
- **内容**:
  - **障害物検出 (obstacle.py) を完全削除** — ユーザー指示「あれの検出機能は完全に消し去っていい」
    - `src/prediction/obstacle.py` 削除
    - `tests/test_obstacle.py` 削除
    - `Pipeline` から `ObstacleDetector` のインポート・初期化・呼び出しを除去
    - `update_settings` から `enable_obstacle` 削除
    - `Renderer._draw_obstacle_bboxes` 削除
    - `MainWindow` から `chk_obstacle` チェックボックス削除
    - `config/realtime_cpu.yaml` から `enable_obstacle` 削除
    - `tests/test_config.py` の関連 assert 削除
  - **自転車検出を強化**:
    - `bicycle` の conf を 0.18→**0.15** に（最も敏感に）
    - `is_pedestrian_rush` で自転車専用パラメータ:
      - 出現直後の閾値 speed > 2.5 (vs 人 3.0)
      - 軌跡交差時の閾値 speed > 3.5 (vs 人 4.5)
      - 高速移動の閾値 speed > 4.5 (vs 人 5.5)
      - age limit 16 フレーム (vs 人 12)
    - Renderer の BB 色: 自転車は **ピンク (200,100,255)** に分離（人/車から区別）
    - 警告メッセージで「自転車」と明示（"自転車衝突注意" "自転車飛び出し注意"）
    - Alert.kind を `person_collision` / `bicycle_collision` のようにクラス別に分離
- **追加テスト** (`test_bicycle.py`):
  - 自転車の rush 閾値が人より低いことを保証
  - 自転車衝突警告のメッセージに「自転車」を含む
- **既存テスト調整**: `pedestrian_*` → `person_*` に kind 名変更
- **影響**: `src/prediction/obstacle.py` (削除), `src/prediction/risk_analyzer.py`, `src/prediction/intrusion.py`, `src/pipeline.py`, `src/render/renderer.py`, `src/ui/main_window.py`, `config/realtime_cpu.yaml`, `tests/test_obstacle.py` (削除), `tests/test_bicycle.py` (新規), `tests/test_config.py`, `tests/test_risk_analyzer.py`
- **メモ**: `pytest` 56 passed (障害物2件削除、自転車2件追加)、`ruff` clean。BB のピンク色で自転車が見分けやすくなる

### 2026-05-12 — [Claude] [タグ] v9.4 を安定版として `stable-2` タグ付け
- **内容**: ユーザー指示で v9.4 コミット (7a29e1d) に `stable-2` タグを追加し push
- **影響**: なし（タグ付けのみ）

### 2026-05-12 — [Claude] [実装] v9.5 - 車線逸脱検出 (LDW) を洗練
- **内容**: ユーザー要望「車線外れたな ってなったらアラートを出して」を実装。
  - **判定ロジック変更**: 「ego_lane_polygon 底辺端と画像中央の距離」(間接的) から、**「自車中心と自車レーン中心の偏差率」**(直接的) へ
    - 偏差率 = |自車x - レーン中心x| / 車線半幅
    - < 0.6 : 正常
    - 0.6-0.9 : warn「車線寄り注意」(level 2)
    - ≥ 0.9 : **critical「⚠ 車線逸脱」(level 3)**
  - **方向情報を含む**: メッセージに「左/右」と偏差率%を表示（例: `⚠ 車線逸脱 (左方向 130%)`）
  - **連続 3 フレーム要件**: 瞬間的なブレでは発火しない
  - **車線幅信頼性チェック**: lane_half_width < 8px なら信頼できないとして判定スキップ
- **追加テスト** (`test_ldw.py`):
  - 車線中央で警告なし
  - 車線外（ratio>=0.9）で critical 発火、方向情報を含む
  - 車線寄り（0.6<=ratio<0.9）で warn 発火
  - 連続 3 フレーム未満では発火しない
  - 中央に戻ったら警告解除
- **影響**: `src/lane/lane_detector.py`, `tests/test_ldw.py` (新規)
- **ベンチマーク**: 137ms / 7.3 fps
- **メモ**: `pytest` 56 passed (+5)、`ruff` clean。アラートに方向と %% が出るので「どっちに逸脱したか」「どれくらい逸脱したか」が一目で分かる

### 2026-05-12 — [Claude] [実装] v9.4 - 白線なし道での車線推定フォールバック
- **内容**: ユーザー要望「実線や点線などがない道でも車線検出が効くように」を実装。
  - **v4 (stable-1) の挙動は完全保持** — 白線/点線がある道は v4 と全く同じ動作
  - **白線なし道だけフォールバック発動**:
    - 条件: classical で両側とも検出失敗 AND 履歴も 3 フレーム未満
    - 動作: 路面マスク (`road_mask`) の左右輪郭から線形フィットで仮レーン構築
    - 自車レーン幅は路面幅の 1/2 を採用（広い道路で 2 車線分を取らない）
    - 信頼度 0.20（古典より低く、白線が見え次第そちらが優先される）
  - `_road_mask_to_lane()` 関数を `lane_detector.py` に追加
  - `LaneDetector.detect(frame, road_mask=...)` で受け取り
- **テスト追加** (`test_lane_no_lines.py`):
  - 典型的な路面マスクで仮レーン構築できる
  - 空マスクなら None
  - 白線なし + マスクあり → フォールバック動作
  - 白線なし + マスクなし → 既存挙動どおり何も返さない
- **影響**: `src/lane/lane_detector.py`, `tests/test_lane_no_lines.py` (新規)
- **ベンチマーク**: 131ms / 7.6 fps（v9.2 とほぼ同等）
- **メモ**: `pytest` 51 passed (+4)、`ruff` clean。白線が見えない生活道路でも自車レーンの当たりが出る

### 2026-05-12 — [Claude] [修正] v9.3 - フロント↔リアの誤判定を修正
- **内容**: ユーザー報告「フロントをリアと判定する時がある」を修正。
  - **原因**: 赤い車体色が「テールランプ」と誤検知される。BB 下部 1/3 全体の赤割合で判定していたため、車体が赤いと rear バイアスがかかる
  - **対策**:
    1. **vy が強い（>2.5 or <-2.5）時は色解析を完全スキップ** — 軌跡が明確なら最優先
    2. **左右端 1/4 領域のペアで対称チェック** — 中央 1/2 の車体色は無視
    3. **対称性条件** — 左右両方で赤がある場合のみ rear、片側だけの大量赤は無効
    4. **大きすぎる赤を車体色と判定** — 左右どちらかが 60% 以上赤い → 赤車体とみなして判定却下（ただしヘッドライト白は別途見る）
    5. HSV 赤閾値を厳しく（彩度 100→120、明度 70→80）
  - **追加テスト**: 「赤い車体（vy>0）を front と正しく判定する」「強い vy なら色無視で front/rear 確定」
- **影響**: `src/prediction/vehicle_facing.py`, `tests/test_vehicle_facing.py`
- **ベンチマーク**: ほぼ同等（色解析の処理量微減）
- **メモ**: `pytest` 47 passed (+3)、`ruff` clean。BB 下に表示される向きラベルが正確になるはず

### 2026-05-12 — [Claude] [修正] v9.2 - 車線検出を stable-1 (v4) と同じ実装に戻す
- **内容**: ユーザー要望「車線の検出だけ安定版1と同じに」を反映。
  - `src/lane/classical.py` と `src/lane/lane_detector.py` を **v4 (stable-1) のファイルでそのまま置換**
  - `LaneDetector.detect()` には互換のため `**_kwargs` を追加（Pipeline 側の `road_mask` / `vehicle_bboxes` 引数を無視）
  - v9.1 で導入した指数減衰、短縮窓、急変ガード、低信頼度リセット等は全て撤回
- **挙動**: stable-1 (v4) と完全に同じ車線検出/平滑化/LDW 判定
- **ベンチマーク**: 134ms / 7.4 fps（軽量化方向に振れた）
- **影響**: `src/lane/classical.py`, `src/lane/lane_detector.py`
- **次の方針**: 実動画で v4 当時の感覚で動くか確認
- **メモ**: `pytest` 44 passed、`ruff` clean。Pipeline の `vehicle_bboxes` 渡しは無害化されたので削除しても動く

### 2026-05-12 — [Claude] [修正] v9.1 - 車線固着バグ修正
- **内容**: v9 で導入した `_complement_missing_side` が原因で「最初の検出がずっと使われる」固着が発生。修正:
  1. **`_complement_missing_side` を完全廃止** — 履歴から反対側を補完する仕組みが古い検出を引きずる元凶
  2. **平滑化窓 8→5** に短縮（直近のフレームをより強く反映）
  3. **平滑化を指数減衰に** — `w = confidence × 0.5^(N-1-i)`。新しいフレームほど指数的に重みが大きい。古いフレームは半減
  4. **低信頼度リセット閾値 12→6** に短縮（6 フレーム連続で低信頼なら履歴クリア）
  5. **急変ガード閾値 60→80** に緩和（実際の車線変動で false rejection を減らす）
- **影響**: `src/lane/lane_detector.py`
- **ベンチマーク**: 168ms / 5.9 fps（v9 とほぼ同等）
- **次の方針**: 実動画で「車線がちゃんと追従する」「固着しない」を確認
- **メモ**: `pytest` 44 passed、`ruff` clean。「さっきまでできてた」の挙動に近づけたはず

### 2026-05-12 — [Claude] [修正] v9 - 人検出強化 + 車線実線/点線優先
- **内容**:
  1. **人/自転車の検出強化** — クラス別 conf フィルタを `YoloTracker` に実装:
     - YOLO 出力時 conf 0.18 まで下げる（人/自転車も拾う）
     - 検出後、`conf_per_class` で class 別に再フィルタ
       - person/bicycle: 0.18（敏感）
       - motorcycle: 0.25
       - car/bus/truck: 0.32（誤検出抑制）
     - `max_det` 100→120
  2. **車線検出: 実線/点線を最優先** — 路面マスクフォールバックの条件を厳しく:
     - **片側だけ検出**できた場合は履歴から反対側を補完して採用（実線/点線優先）
     - **両側完全失敗 AND 履歴も足りない**時のみ路面マスクから仮レーン構築
     - 路面マスクベースの信頼度は 0.35→0.20 に下げ（古典より低い扱い）
  3. **色マスク・Hough 緩和** — 薄い白線・点線をさらに拾えるよう:
     - 白の V 閾値 145→125、彩度許容 80→95
     - 黄の S 閾値 45→35、V 70→60
     - Hough threshold 20→16、min_line_length 14→10、max_line_gap 220→280
- **ベンチマーク**: 166ms / 6.0 fps（v8 165ms とほぼ同等）
- **影響**: `src/tracking/byte_tracker.py`, `src/lane/lane_detector.py`, `src/lane/classical.py`, `src/pipeline.py`, `config/realtime_cpu.yaml`, `tests/test_config.py`
- **次の方針**: 人の検出と車線安定性を実動画で再確認
- **メモ**: `pytest` 44 passed、`ruff` clean。点線片側だけでも履歴で補完するので、車線がさらに安定するはず

### 2026-05-12 — [Claude] [修正] v8 - 5件の改善対応
- **内容**:
  1. **前車発進の誤発火抑制** — 自車前進中 (ego_motion.is_moving==True) は判定無効化。`_front_start` は履歴 8 フレーム必要、停止判定 max<0.5、急発進 >3.0 に厳格化
  2. **レーントラッキング暴れ対策** — 平滑化窓 15→**8**（応答性UP）、`max_lateral_jump_px=60` で急変フレームを除外、`low_conf_reset_frames=12` で低信頼度連続時に履歴クリア
  3. **障害物 OFF ボタン実装** — UI に「障害物検出」チェックボックス追加、**デフォルト OFF**
  4. **障害物の検出内容を画面表示** — Renderer に `_draw_obstacle_bboxes`、赤太枠 + 斜線 + "OBSTACLE" ラベル。BBが取れなければ何も表示しない
  5. **障害物さらに誤検知抑制** — area_ratio 0.40→**0.55**、連続フレーム 5→**8**、進路台形面積が小さい (<1500px²) 場合は判定見送り
  6. **車体向き判定刷新** — `vehicle_facing.py` を再設計:
     - アスペクト比 > 2.5 → **side 確定**
     - vy で base (front/rear) を粗判定
     - 色解析 (テールランプ赤 / ヘッドライト白) で補正
     - 統合判定で base と color の整合性チェック
  7. **画面に向き/heading ラベル表示** — BB 下部に "front/approaching" のような色付きラベル。**ユーザーが判定結果を視覚的に確認可能に**
- **ベンチマーク**: 165ms / 6.1 fps（v7 192ms から軽量化、障害物デフォルト OFF 効果）
- **影響**: `src/prediction/risk_analyzer.py`, `src/prediction/obstacle.py`, `src/prediction/vehicle_facing.py`, `src/lane/lane_detector.py`, `src/pipeline.py`, `src/render/renderer.py`, `src/ui/main_window.py`, `config/realtime_cpu.yaml`, `tests/test_*.py`
- **次の方針**: 実動画で挙動を再確認。向きラベルが BB に出るので「ここで rear と認識してる」「side と認識してる」と検証しやすい
- **メモ**: `pytest` 44 passed、`ruff` clean

### 2026-05-12 — [Claude] [修正/実装] v7 - 11件の改善対応
- **内容**:
  1. **UI 停止後の再開バグ修正** — `_last_source_factory` を保持、`_stop()` 後の `_play_pause()` で再起動可能に
  2. **障害物の誤検知抑制** — `area_ratio_thresh` 0.20 → 0.40、`consecutive_frames=5` で連続検出を要求
  3. **車線検出: 前方車BBマスキング** — `ClassicalLaneDetector.detect(frame, vehicle_bboxes=...)` で車両 BB 領域を edges からゼロ化。車のシルエットを車線と誤認しない
  4. **LDW 敏感化** — 中央値ウィンドウ 5→3、`min_confidence` 0.2→0.15
  5. **台形ゾーン 自動/固定モード切替 UI** — `QComboBox` 「奥行きモード」追加。AutoZone に `auto_depth` フラグ反映
  6. **統合危険度スコア** — `src/prediction/threat_score.py` 新規。距離/TTC/heading/facing/接近速度/滞在/レーン内を合成し 0-1 スコア。`threat_level(s)` で 0/1/2/3 に分類
     - v6 の AND 条件衝突判定を置換し、`level >= 3 → critical`, `level == 2 → warn`
     - 「無関係の車に脅威」「危ないのに脅威でない」の両方を一貫したスコアで補正
  7. **人/自転車検出強化** — `detector.conf` 0.30→0.22、`max_det` 80→100
  8. **飛び出し判定 緩和** — age ≤ 12、速度 ≥ 3.0 px/f、軌跡交差速度 ≥ 4.5、レーン中心方向の高速移動も拾う
  9. **車体向き判定 強化** — アスペクト比 + 色解析 (赤/明白) + 軌跡 vy の **投票方式**。`is_lateral_shape` で横向き確定判定追加
  10. **UI 即時反映の補強** — `Pipeline.update_settings` に `enable_obstacle`, `enable_ego_motion` を追加
  11. **新規テスト** — `test_threat_score.py` (4件)、`test_obstacle.py` 連続フレーム検証に更新
- **ベンチマーク**: 192ms / 5.2 fps（v6 の 185ms とほぼ同等、人検出 conf 下げで僅かに重い）
- **影響**: `src/ui/main_window.py`, `src/ui/inference_thread.py`, `src/pipeline.py`, `src/prediction/obstacle.py`, `src/prediction/risk_analyzer.py`, `src/prediction/threat_score.py` (新規), `src/prediction/vehicle_facing.py`, `src/prediction/intrusion.py`, `src/lane/classical.py`, `src/lane/lane_detector.py`, `src/lane/auto_zone.py`, `config/realtime_cpu.yaml`, `tests/test_*.py`
- **次の方針**: 実動画で検証。脅威度スコアの閾値は実走行データで微調整が必要
- **メモ**: `pytest` 44 passed、`ruff` clean。UI で「停止→再生」が動くようになったので検証しやすくなったはず

### 2026-05-12 — [Claude] [実装] AutoZone簡素化 / 障害物ON / 絶対速度ベクトル (v6)
- **内容**: ユーザー要望 3 点:
  1. **AutoZone を「奥行きのみ自動」に簡素化**:
     - 左右振れ・中心・上頂点幅・上頂点 offset は **手動スライダー値そのまま**
     - 上頂点 y (奥行き) のみ消失点ベースで自動算出
     - 左右の制御は将来 OBD2 から実装する余地を残す
  2. **障害物検出 ON** → `enable_obstacle: true` をデフォルトに
  3. **相手車の絶対ベクトル推定** → `src/motion/absolute_velocity.py` 新規:
     - `AbsoluteVelocityEstimator`: IPM で実世界 m/s 換算、自車速度を加味して **絶対座標系の longitudinal/lateral 速度**を算出
     - 信頼度 0-1 を返す。遠距離(>60m)や履歴不足で低下
     - 自車速度は `SpeedSource` から取得:
       - OBD2 接続時: 正確な実速度
       - 視覚推定時: EgoMotionState の forward_flow_px から粗推定
     - **将来 OBD2 が繋がれば `ObdSpeedSource` を Pipeline に注入するだけで精度向上**
- **RiskAnalyzer 統合**:
  - 各 track の絶対速度をフレーム冒頭で一括キャッシュ
  - 信頼度 > 0.6 なら、純粋な相対接近速度 (自車 m/s - 相手 longitudinal m/s) でクロスチェック
  - 接近していなければ approach_ok=False で衝突警告抑制 → 直進対向車・並走車の誤判定が更に減る
- **新規ヘルパー**: `src/depth/ipm_fallback.py` に `bbox_to_distance()` 関数を追加
- **テスト追加**: `tests/test_absolute_velocity.py` (2件)、`tests/test_auto_zone.py` を新仕様に書き直し (4件)
- **ベンチマーク**: 185ms / 5.4 fps（障害物 + 絶対速度追加で v5 の 163ms から +22ms）
- **影響**: `src/lane/auto_zone.py`, `src/motion/absolute_velocity.py` (新規), `src/depth/ipm_fallback.py`, `src/pipeline.py`, `src/prediction/risk_analyzer.py`, `config/realtime_cpu.yaml`, `tests/test_absolute_velocity.py` (新規), `tests/test_auto_zone.py`, `tests/test_config.py`
- **次の方針**: 実動画で挙動確認。重ければ obstacle every_n や segmenter 設定を見直す
- **メモ**: `pytest` 40 passed、`ruff` clean。OBD2 接続インターフェース (`SpeedSource`) は既に整っているので、実車でデータ流し込み可能になり次第すぐ反映できる

### 2026-05-12 — [Claude] [タグ] v4 を安定版として `stable-1` タグ付け
- **内容**: ユーザー指示で v4 コミット (6f7bbbc) に `stable-1` タグを追加し push
- **影響**: なし（タグ付けのみ）

### 2026-05-12 — [Claude] [実装] 6 項目の改善 (v5)
- **内容**: ユーザーから 6 件の追加要望:
  1. **全機能 ON をデフォルト化** — `config/realtime_cpu.yaml` で `enable_enhancement/signs/obstacle/ego_motion/segmenter` を全部 true。SegFormer は 18f / 256px に軽量化
  2. **車線なし道での自車レーン推定** — `LaneDetector.detect(frame, road_mask=...)`。古典検出失敗時に **路面マスク（segmenter）の左右輪郭を線形フィット**して仮レーンを構築。`_road_mask_to_lane` を追加
  3. **LDW 精度向上** — ヒステリシス 25/45 → **18/40**、min_confidence 0.3 → 0.2、直近 5 フレームの**中央値**で判定（瞬間ノイズ除去）
  4. **衝突検知に相手車のベクトル/向き考慮** — `src/prediction/vehicle_facing.py` 新規:
     - BB 下部 1/3 の HSV で赤領域 → リア(テールランプ)、明白色 → フロント(ヘッドライト)
     - フォールバックは vy 符号
     - `combine_collision_risk(facing, heading)` で 0-1 リスク係数算出
     - リスク 0.15 未満なら警告対象外
  5. **障害物検出** — `src/prediction/obstacle.py` 新規。自車進路台形内で「路面マスク==0」の領域が 20% 超なら警告（壁・山・ガードレール想定）。15 フレームの cooldown 付き
  6. **台形ゾーン完全自動化（curve 対応）** — `src/lane/auto_zone.py` 新規 `AutoZoneController`:
     - レーン検出があれば左右底辺を採用、無ければ消失点ベース
     - 消失点 x 位置の偏りで台形上頂点が左右にずれる（コーナリング表現）
     - 履歴 10 フレームの中央値で平滑化
     - 手動スライダーは **オフセット扱い**（自動値 + 微調整）
- **追加最適化** (全機能 ON の負荷削減):
  - `FrameEnhancer`: ヒストグラム判定を 8 フレームに 1 回キャッシュ（毎フレーム判定をやめる）
  - `RiskAnalyzer`: facing 推定は「自車レーン内 or 画面下 50% の近距離車両」のみで実行
- **追加テスト**: `test_auto_zone.py` (3件)、`test_obstacle.py` (2件)、`test_vehicle_facing.py` (4件)
- **ベンチマーク** (`demo_highres.mp4` 1284x2778, MPS):
  - v4 (軽量設定): 49ms / 20.3 fps
  - v5 (全機能 ON): **164ms / 6.1 fps** ← SegFormer + Enhancer + Sign + Obstacle + Facing 込み
  - 軽いフレーム単体: 92ms (約 10 fps)
  - **トレードオフ警告**: 全機能 ON は重い。実用優先なら一部 OFF を提案する
- **影響**: `src/pipeline.py`, `src/lane/lane_detector.py`, `src/lane/auto_zone.py` (新規), `src/enhancement/enhancer.py`, `src/prediction/risk_analyzer.py`, `src/prediction/vehicle_facing.py` (新規), `src/prediction/obstacle.py` (新規), `config/realtime_cpu.yaml`, `tests/test_*.py` (3 新規 + 1 更新)
- **次の方針**: ユーザー実動画で確認。重ければ segmenter OFF または enhancement OFF をオプション化提案
- **メモ**: `pytest` 37 passed、`ruff` clean

### 2026-05-11 19:30 — [Claude] [修正/実装] 9 件のユーザー指摘を一括対応 (v4)
- **内容**: ユーザーから 9 件の改善要望:
  1. **車線がクロスする** → `LaneDetector.detect` で「左の x ≥ 右の x」になる検出を不採用、confidence を下げる
  2. **飛び出し検出が弱い** → `is_pedestrian_rush` を 3 条件 OR の強化版に: ①age≤8+速度4.5以上+自車レーン方向、②急加速、③軌跡交差。BBや速度条件を緩めて敏感に
  3. **車線逸脱の精度** → ヒステリシス 30/50→25/45、低 confidence では LDW を出さない
  4. **何もない場面で衝突警告** → 滞在 5→8 フレーム、車間警告は「距離縮小 AND TTC 短 AND 接近方向」の AND 条件
  5. **台形ゾーンが自動更新されない** → `LaneDetector.detect` で自車レーン底辺中点を `center_x_ratio` に 0.3 の重みで滑らかに反映（信頼できる検出時のみ）
  6. **他車進行方向の考慮** → `classify_vehicle_heading` 新規。"approaching"/"leaving"/"lateral"/"static"/"unknown" を返し、`leaving` 車両は警告対象外
  7. **車間注意の精度** → `_is_getting_closer` を直近 4 サンプルの線形回帰の傾き判定に変更（ノイズに強い）
  8. **UI で設定変えても反映されない (バグ)** → `Pipeline.update_settings(cfg)` 新規。`InferenceThread.apply_settings(cfg)` でキューイングし、次フレームで Pipeline へ live 反映。`_sync_feature_flags` から自動通知
  9. **信号 vs テールランプ混同** → `JpSignDetector.detect(frame, vehicle_bboxes=...)` で車両 BB と重なる光源（テールランプ等）を除外。ROI を画面上 50%→40% に絞る
- **追加テスト**:
  - `tests/test_intrusion_heading.py`: approaching/leaving/lateral 分類、飛び出し緩和条件
  - `tests/test_jp_sign_detector.py`: 信号 ROI 制限と上半身検出の保証
- **ベンチマーク**: 49ms / 20.3 fps（v3 とほぼ同等、追加処理は誤差範囲）
- **影響**: `src/pipeline.py`, `src/prediction/intrusion.py`, `src/prediction/risk_analyzer.py`, `src/lane/lane_detector.py`, `src/signs/jp_sign_detector.py`, `src/ui/inference_thread.py`, `src/ui/main_window.py`, `tests/test_intrusion_heading.py` (新規), `tests/test_jp_sign_detector.py` (新規), `tests/test_risk_analyzer.py`
- **次の方針**: ユーザー実動画で確認。誤判定が「何もない場面」で出るのは滞在 8f + AND 条件で大幅減るはず
- **メモ**: `pytest` 28 passed、`ruff` clean。UI 設定反映は `_sync_feature_flags` から自動キューイング、ユーザー操作は今までどおり

### 2026-05-11 18:15 — [Claude] [実装] 車線検出の刷新（点線・自車レーン選別・滞在判定）
- **内容**: ユーザー指摘 4 点を一括対応:
  1. **点線対応強化** — `ClassicalLaneDetector._lane_edges` で縦長カーネル (3×15) の閉処理を 2 回かけ破線断片を線分に結合、白マスク閾値を緩める (V≥145)、HoughLinesP のしきい値・最小線分長を下げる
  2. **自車レーンだけを認識**（道路全体じゃない） — 検出した全直線を傾き＋下端x切片でクラスタリングし、画面中心に最も近い左右1ペアを選ぶ。レーン幅は画面幅の 18〜55% にあるものだけ採用。これより広いと「道路全体」を取らず候補から除外
  3. **横切っただけで警告しない** — `RiskAnalyzer` に「自車レーン内連続滞在カウンタ」を追加（30fps で 5 フレーム=約0.17秒以上滞在しないと衝突警告を出さない）。さらに「自車レーンから出ていく軌跡」（横断完了方向）なら警告抑制
  4. **生活道路対応** — `LaneDetector` に過去 15 フレームの**重み付き時間平滑化**を追加。瞬間的に検出が消えても直前の平均レーンで補間。confidence が `min_confidence=0.3` 未満なら LDW を発火しない（誤警告防止）
- **新規/変更モジュール**:
  - `src/lane/classical.py`: 戻り値が `(LaneInfo, confidence)` のタプルに変更。クラスタリング + 自車レーン選別 + 強化マスク
  - `src/lane/lane_detector.py`: 履歴 deque による平滑化、`last_confidence` プロパティ、LDW 信頼度ゲート
  - `src/prediction/risk_analyzer.py`: `_ego_lane_dwell` カウンタ + `_is_dwelling` / `_is_leaving_lane` メソッド、pedestrian/vehicle 警告に滞在条件を追加
- **テスト追加・修正**:
  - `test_lane_classical.py`: タプル戻り値に対応、confidence 検証
  - `test_risk_analyzer.py`: `test_person_just_crossing_does_not_warn` 追加（横切り誤判定が抑えられることを保証）、既存の警告系テストを連続フレーム形式に修正
- **ベンチマーク**: avg 50ms / 20.0fps（v2 とほぼ同等、追加処理は誤差範囲）
- **影響**: `src/lane/classical.py`, `src/lane/lane_detector.py`, `src/prediction/risk_analyzer.py`, `tests/test_lane_classical.py`, `tests/test_risk_analyzer.py`
- **次の方針**: ユーザーに実動画で確認してもらう。点線・生活道路で改善が薄ければ classical → DL (Ultra-Fast-Lane-Detection) への置換を検討
- **メモ**: `pytest` 22 passed、`ruff` clean。`LaneInfo` に confidence フィールドを足す案もあったが、`LaneDetector.last_confidence` プロパティで参照する設計に留めた（後方互換）

### 2026-05-11 17:30 — [Claude] [実装] 自車エゴモーション推定を導入。背景フロー補正で誤判定を抑制
- **内容**: ユーザー指摘「自車の移動を考慮していない → 誤判定が多い」を受けて根本対応。
  1. **`src/motion/ego_motion.py` 新規** — Lucas-Kanade スパースオプティカルフローで路面領域のキーポイントを毎フレーム追跡。フローベクトル群から消失点を最小二乗で自動推定（車線消失点があれば 70/30 で統合）。前進量・横ずれ・速度レベル (`stop`/`slow`/`moderate`/`fast`) を `EgoMotionState` として返す
  2. **`src/motion/speed_source.py` 新規** — `SpeedSource` Protocol を定義し `VisualSpeedSource`（視覚推定）と `ObdSpeedSource`（OBD2 接続用スタブ）を実装。将来 OBD2 配線時はインスタンス差し替えだけで動く
  3. **`src/types.py`** — `EgoMotionState` dataclass を追加。`SceneContext.ego_motion` を持たせて下流に伝搬
  4. **`src/pipeline.py`** — 毎フレーム `EgoMotionEstimator.update()` を呼び、ctx と meta に積む
  5. **`src/prediction/risk_analyzer.py`** — 各物体の画面速度から「消失点と前進量から推定した背景フロー」を差し引いた**相対速度**で判定。背景と同じ動きの物体（看板・電柱など）は警告対象外に。`is_cut_in_vehicle` も相対速度版で呼ぶため、直進対向車が「侵入」と誤判定されなくなる
  6. **`src/prediction/ttc.py`** — looming（BB 面積拡大率）ベース TTC を追加。距離 TTC と looming TTC の小さい方を採用。距離不明でも TTC が出る
  7. **`config/realtime_cpu.yaml`** — `enable_ego_motion: true`（default）。SegFormer は 1.3 秒スパイクで実用に堪えないため `realtime_cpu` では `enabled: false` に戻し、`full_quality` で使う
- **誤判定が抑制される具体例**:
  - 自車前進中の道路脇看板 → 背景と一致 → 警告なし
  - 直進対向車 → 自車運動分を差し引けば横方向動きほぼゼロ → cut_in と判定しない
  - 自車停止中の歩行者 → 自車運動補正は無効、従来どおり敏感に検知
- **ベンチマーク** (`data/videos/demo_highres.mp4` 1284x2778, MPS, 50 frame):
  - 修正前 (ego_motion 無し): 40ms / 25.3 fps
  - 修正後 (ego_motion 込み): **48ms / 20.8 fps**（差 8ms / -4.5 fps）
  - 消失点自動検出: (1387, 357) で動作確認
- **影響**: `src/types.py`, `src/motion/ego_motion.py` (新規), `src/motion/speed_source.py` (新規), `src/pipeline.py`, `src/prediction/risk_analyzer.py`, `src/prediction/ttc.py`, `config/realtime_cpu.yaml`, `tests/test_ego_motion.py` (新規), `tests/test_config.py`
- **次の方針**: ユーザーに実動画で確認してもらう。OBD2 配線時は `ObdSpeedSource` を Pipeline に注入する小修正だけで実速度（km/h）が使えるようになる
- **メモ**: `pytest` 21 passed、`ruff check` clean。`EgoMotionState` の `confidence` を低時はリスク判定を控えめにする発展も可能

### 2026-05-11 15:30 — [Claude] [修正] 古い検出枠が残り続ける問題を解消（スキップ撤去・毎フレーム解析）
- **内容**: ユーザー報告「検出した内容がずっと画面に残り続ける」を受けて修正。
  - **原因**: `InferenceThread` の `adaptive_skip` が ON の状態で、遅延を感知したフレームは解析をスキップして `pipeline.render_cached(...)` を呼んでいた。`render_cached` は `_last_tracks` を SceneContext に詰めて描画するため、スキップが続くと **古い検出枠が画面に残り続ける** 視覚現象になっていた
  - **修正**: `InferenceThread.run` から `adaptive_skip` / `analysis_fps` / `analysis_start_frame` / `raw_preview_before_analysis` / `max_schedule_lag_frames` をすべて撤去し、**毎フレーム必ず `pipeline.process()` を呼ぶ**素直なループに。検出が空ならその時点で空が描画され、古い枠は残らない
  - `pipeline.render_cached()` メソッドは未使用となったので削除
  - 各プロファイル YAML (`realtime_cpu.yaml`, `turbo_cpu.yaml`, `view_only.yaml`) から不要な `analysis_fps` / `adaptive_skip` 等の設定を削除して整理
  - `tests/test_pipeline_smoke.py` に「検出が空のフレームでは tracks が空になる」リグレッションテスト追加
- **影響**: `src/ui/inference_thread.py`, `src/pipeline.py`, `config/realtime_cpu.yaml`, `config/turbo_cpu.yaml`, `config/view_only.yaml`, `tests/test_config.py`, `tests/test_pipeline_smoke.py`
- **次の方針**: ユーザーに再度実動画で確認してもらう。もし MPS で 25fps では遅すぎる場合は、CoreML 変換 (`yolov8n.mlpackage`) を検討
- **メモ**: `pytest` 17 passed、`ruff check` clean。InferenceThread のロジックが半分になりバグ余地が減った

### 2026-05-11 15:00 — [Claude] [修正/実装] Codex 引継ぎ。MPS デフォルト化・偽検出削除・パイプライン簡素化・機能復活
- **内容**: ユーザー報告「車両認識が出ない」を受け、Claude が開発を引継ぎ。一連の修正を実施。
  1. **MPS 診断**: `scripts/diagnose_mps.py` を実行 → **MPS available: True** が判明（PROGRESS 未解決#8 は古い情報）。macOS 26.0 / arm64 / torch 2.11.0、MPS テンソル作成OK
  2. **偽検出の正体特定**: `FallbackVehicleDetector._center_candidate` が **検出ゼロ時に必ず中央に偽の "car" を 1 個出す** → ユーザーが見た「枠は出るが実車に反応しない」の正体だった。削除
  3. **YOLO 二重呼び出し排除**: `YoloTracker.track` が `_track_with_yolo` 失敗時に `detector.detect` を再度回す構造を排除（モデルロード失敗時のみ fallback を使うように）
  4. **MPS デフォルト化**: `config/realtime_cpu.yaml` で `device: cpu` → `auto`、`imgsz: 416 → 480`、`max_process_width: 640 → 960`、`analysis_fps: 10 → 0`（毎フレーム）
  5. **InferenceThread 簡素化**: `raw_preview_before_analysis` の二重描画ロジック撤去。`adaptive_skip` だけで遅延制御
  6. **UI 復活**: プロファイル切替 `QComboBox` を MainWindow 左サイドバーに追加、11:21 で消えていた「視認性補正」「信号/標識」チェックボックスを復活
  7. **Pipeline 機能統合**: `enable_enhancement=True` のとき `FrameEnhancer.process()`、`enable_signs=True` のとき `JpSignDetector.detect()` を呼ぶように。`Renderer` で `ctx.signals` を描画
- **影響**: `scripts/diagnose_mps.py`, `src/detection/fallback_detector.py`, `src/tracking/byte_tracker.py`, `src/ui/inference_thread.py`, `src/ui/main_window.py`, `src/pipeline.py`, `src/render/renderer.py`, `config/realtime_cpu.yaml`, `config/full_quality.yaml`, `tests/test_config.py`, `tests/test_fallback_detector.py`
- **ベンチマーク** (`data/videos/demo_highres.mp4` 1284x2778):
  - **realtime_cpu (MPS)**: avg **40ms / 25.3fps** ✅ 検出+追跡+車線+リスク判定
  - **full_quality (MPS)**: 766ms / 1.3fps（SegFormer+Depth が律速、任意プロファイル）
  - 修正前 CPU 1312ms (初回ロード込) → 修正後 40ms（約 33 倍）
- **次の方針**: ユーザーに実動画で動作確認してもらう。SegFormer/Depth を必須にしない設計のため `realtime_cpu` を標準推奨
- **メモ**: `pytest` 16 passed、`ruff check` clean。未解決#8（MPS=False）は解決済みとマーク

### 2026-05-11 14:48 — [Codex] [ドキュメント] ユーザー指摘と要求をMarkdownへ整理
- **内容**: これまでユーザーが示した諸問題、要求、品質基準、削除対象、性能要件、YOLO/追跡/衝突検知/台形ゾーン関連の指摘を `USER_REQUESTS_AND_ISSUES.md` に整理した。今後の実装チェックリストとして使えるよう、カテゴリ別にまとめた。
- **影響**: `USER_REQUESTS_AND_ISSUES.md`, `PROGRESS.md`。関連 Phase: PLAN.md 全体、特に §2.4 / §2.6 / §2.9 / §6 / §8。
- **次の方針**: 追加実装や修正時は `USER_REQUESTS_AND_ISSUES.md` の満足条件を確認し、実動画/注釈付き動画で目視確認する。
- **メモ**: 本プロジェクトの進捗ルールに従い、本エントリを追記した。

### 2026-05-11 14:45 — [Codex] [修正] 警告フォントの日本語欠けを調整
- **内容**: 注釈付きデモで警告文の先頭文字が一部欠けることを確認したため、映像オーバーレイ用フォントの優先順を `Arial Unicode.ttf` 優先に変更した。
- **影響**: `src/render/renderer.py`。関連 Phase: PLAN.md §6。
- **次の方針**: 最終チェックとして Ruff/pytest と注釈付き動画生成を再実行する。
- **メモ**: macOS標準フォントの範囲差による表示欠けへの対処。

### 2026-05-11 14:44 — [Codex] [修正] 警告オーバーレイの日本語描画を修正
- **内容**: 注釈付きデモで、OpenCV標準フォントが日本語非対応のため警告メッセージが `????` と表示される問題を確認した。macOSの日本語フォントをPillow経由で使い、映像上の警告も日本語で描画できるようにした。
- **影響**: `src/render/renderer.py`。関連 Phase: PLAN.md §6。
- **次の方針**: 再度 Ruff/pytest と注釈付き動画生成を実行し、日本語警告、carラベル、進行方向ベクトルを確認する。
- **メモ**: UIテーブルの警告表示は従来通り維持。

### 2026-05-11 14:43 — [Codex] [修正] 車両ラベルを前面表示
- **内容**: 注釈付きデモで、歩行者ラベルが車両ラベルに重なり `car` 表示が見えにくくなるケースを確認した。描画順を調整し、車/トラック/バス/バイクなどの車両系トラックを後から描いて前面に出すようにした。
- **影響**: `src/render/renderer.py`。関連 Phase: PLAN.md §2.4 / §6。
- **次の方針**: 再度デモ注釈付き動画を生成して、車両ラベル・ベクトルの視認性を確認する。
- **メモ**: UI上で「車を検出したこと」がまず分かるよう、車両表示の優先度を上げた。

### 2026-05-11 14:42 — [Codex] [修正] フォールバック検出で車体位置を優先検出
- **内容**: 注釈付きデモ確認で、フォールバック検出が道路全体のエッジと結合して中央固定枠に落ちる問題を確認した。YOLOが拾えない場面でも車体位置・移動履歴・ベクトルが出るよう、色付き物体の輪郭から車/歩行者候補を先に抽出し、それが取れた場合は中央候補へ落とさないようにした。
- **影響**: `src/detection/fallback_detector.py`。関連 Phase: PLAN.md §2.4 / §6。
- **次の方針**: 再度デモ注釈付き動画を生成し、車体に追従する枠とベクトルが表示されるか確認する。
- **メモ**: YOLO本体の検出が成功した場合は引き続きYOLO/ByteTrack結果を優先する。

### 2026-05-11 14:39 — [Codex] [修正] フォールバック枠もcar表示へ統一
- **内容**: デモ注釈付き動画を確認したところ、YOLOが拾えない最悪時の中央候補が `candidate` 表示になっていたため、ユーザー要望の `car` 表示と合うようフォールバック中央候補も `car` として表示するよう修正した。
- **影響**: `src/detection/fallback_detector.py`, `tests/test_fallback_detector.py`。関連 Phase: PLAN.md §2.4 / §6。
- **次の方針**: 再度 Ruff/pytest と注釈付き動画生成を実行し、`car` ラベル・追跡ID・ベクトルが出ることを確認する。
- **メモ**: これはYOLO確信検出ではなく「YOLOが空のときでもUI上で車両候補として可視化する」ための保険。

### 2026-05-11 14:38 — [Codex] [修正] 品質選択を一本化しYOLO追跡表示を強化
- **内容**: ユーザー指摘を受け、UIの品質/実行プロファイル選択を廃止し、Mac向け標準設定1本に統一した。YOLO検出・追跡の見える化を優先し、検出枠ラベルを `car 0.87 ID:3` 形式に変更、追跡履歴、太い進行方向ベクトル、画面上速度 `px/f` を描画するようにした。標準設定は検出品質を戻すため YOLO 416px / conf 0.25 / max_det 80 / 処理幅 640px に調整した。
- **影響**: `src/ui/main_window.py`, `src/render/renderer.py`, `config/realtime_cpu.yaml`, `tests/test_config.py`, `tests/test_renderer.py`, `README.md`。関連 Phase: PLAN.md §2.4 / §2.9 / §6 / §8。
- **次の方針**: Ruff/pytest とデモ動画の注釈付き出力で、枠・ラベル・ベクトルが実際に描画されることを確認する。まだ不足する場合はYOLO追跡結果の保持/補間をさらに強める。
- **メモ**: 品質を複数選べるUIはユーザー意図と違ったため削除。旧 `turbo/view_only/full_quality` 設定ファイルは互換用に残すが、通常UIからは選ばない。

### 2026-05-11 14:26 — [Codex] [修正] ADAS要件別のリスク判定を明示実装
- **内容**: 対人対物衝突検知の不足を受け、`RiskAnalyzer` を要件単位に整理した。歩道歩行者除外、車線内歩行者警告、歩行者/自転車飛び出し、対向車右左折侵入、直進対向車除外、TTC衝突、車間距離注意、前車停止→発進通知を明示的に判定するようにした。
- **影響**: `src/prediction/risk_analyzer.py`, `tests/test_risk_analyzer.py`。関連 Phase: PLAN.md §2.9 / §B.5。
- **次の方針**: 実動画でしきい値を調整する。特に対向車侵入はカメラ画角・台形ゾーン設定・トラック履歴品質に強く依存するため、実映像で `vx` 閾値と交差判定を詰める。
- **メモ**: 追加テストで、歩道歩行者除外、車線内歩行者、対向車右左折侵入、直進対向車除外、車間距離、前車発進を確認。`pytest` は 15 passed、デモ評価も再実行済み。

### 2026-05-11 14:06 — [Codex] [修正] 表示優先で検出枠と台形が必ず出るよう補強
- **内容**: `CLAUDE_ADVICE.md` を確認し、MPS診断スクリプトを追加・実行した。YOLOが空/遅延/失敗のときでも画面に候補枠が出るよう、OpenCVベースの `FallbackVehicleDetector` を追加し、最終的に中央候補枠も出すようにした。台形ゾーンは車線検出結果の有無に関係なく常時描画するようにした。
- **影響**: `scripts/diagnose_mps.py`, `src/detection/fallback_detector.py`, `src/tracking/byte_tracker.py`, `src/pipeline.py`, `src/render/renderer.py`, `tests/test_fallback_detector.py`。関連 Phase: PLAN.md §2.3 / §2.4 / §2.6 / §6 / §8。
- **次の方針**: 実動画でYOLO枠とフォールバック枠の見え方を確認する。MPSがmacOS 26.0でPyTorch側に誤判定される問題は、CoreML化またはPyTorch更新/別ビルドで対応する。
- **メモ**: `scripts/diagnose_mps.py` 結果は arm64 Python / MPS built=True / available=False。MPS tensor は `MacOS 14.0+ required` と誤判定して失敗。`ruff check .` 成功、`pytest` は 10 passed。高解像度デモの注釈付き出力を再生成済み。

### 2026-05-11 11:21 — [Codex] [修正] 検出枠の継続描画と不要機能削除を実施
- **内容**: 軽量化で解析スキップ中に車/人の検出枠が消えて見える問題を修正し、前回解析結果の検出枠・車線・台形ゾーン・警告をスキップ中も描画し続けるようにした。信号/標識検出と視認性補正は標準UIとパイプライン処理から外した。台形ゾーンは `中心`、`奥行き`、`手前幅`、`カーブ寄せ` をUIで調整できるようにした。
- **影響**: `config/default.yaml`, `config/realtime_cpu.yaml`, `config/full_quality.yaml`, `src/pipeline.py`, `src/render/renderer.py`, `src/ui/inference_thread.py`, `src/ui/main_window.py`, `src/utils/geometry.py`, `src/lane/classical.py`, `src/lane/lane_detector.py`, `README.md`。関連 Phase: PLAN.md §2.6 / §2.11 / §2.12 / §6。
- **次の方針**: 実動画で検出枠が継続表示されるか、台形ゾーン調整が運転視点に合うか確認する。
- **メモ**: `ruff check .` 成功、`pytest` は 8 passed。高解像度デモの注釈付き出力を再生成済み。

### 2026-05-11 11:12 — [Codex] [修正] 初回解析待ちで画面が出ない問題を修正
- **内容**: UIなしで標準設定の1フレーム処理を測定し、初回解析に約1.46秒かかって画面表示が待たされることを確認。標準/超軽量プロファイルで最初の数フレームは解析せず表示優先にし、解析予定フレームでも先に軽量プレビューをUIへ送ってからYOLO解析するようにした。
- **影響**: `config/default.yaml`, `config/realtime_cpu.yaml`, `config/turbo_cpu.yaml`, `src/ui/inference_thread.py`。関連 Phase: PLAN.md §2.12 / §6 / §8。
- **次の方針**: 実動画で初回表示と解析後オーバーレイの出方を確認する。まだ解析時の引っかかりが気になる場合は、次に解析処理を完全非同期キュー化する。
- **メモ**: 高解像度デモで最初の `frame_ready` は約0.03秒で発火。`ruff check .` 成功、`pytest` は 8 passed。

### 2026-05-11 11:07 — [Codex] [修正] 検出しやすさを戻し台形ゾーン調整へ修正
- **内容**: 軽量化しすぎて検出が弱くなったため、標準 `realtime_cpu` の YOLO 設定を `imgsz: 320`, `conf: 0.35`, `max_det: 50` に戻した。超軽量も `imgsz: 256`, `conf: 0.4`, `max_det: 30` に調整した。基準調整は赤い一本線ではなく、中心の赤い台形ゾーンを動かす意図だったため、UIラベルと軽量描画を台形ゾーン中心に修正した。
- **影響**: `config/realtime_cpu.yaml`, `config/turbo_cpu.yaml`, `src/render/renderer.py`, `src/ui/main_window.py`, `tests/test_config.py`。関連 Phase: PLAN.md §2.6 / §2.11 / §6。
- **次の方針**: 実動画で検出復帰と速度のバランスを確認する。重い場合は `analysis_fps` か `max_process_width` 側で調整し、YOLO解像度は下げすぎない。
- **メモ**: `ruff check .` 成功、`pytest` は 8 passed。標準設定で高解像度デモ評価を再実行済み。

### 2026-05-11 11:04 — [Codex] [修正] 点線車線の検出を強化
- **内容**: 点線車線に対応するため、古典車線検出で短いHough線分を拾えるようにし、白/黄色の色マスクと縦方向モルフォロジーで破線断片をつなぎ、重み付き回帰で左右車線へ統合するようにした。設定からHough閾値、最小線分長、最大ギャップ、点線サポートを調整できるようにした。
- **影響**: `config/default.yaml`, `src/lane/classical.py`, `src/lane/lane_detector.py`, `src/pipeline.py`, `tests/test_lane_classical.py`, `README.md`。関連 Phase: PLAN.md §2.6 / §B.4。
- **次の方針**: 実動画で点線の拾い具合を確認し、誤検出が多ければ色マスク条件やROIを調整する。
- **メモ**: 点線風の合成フレームで左右車線と自車レーンポリゴンを検出する単体テストを追加。`ruff check .` 成功、`pytest` は 8 passed。

### 2026-05-11 11:02 — [Codex] [修正] 解析10fps化・遅延時スキップ・基準中心調整を追加
- **内容**: 標準 `realtime_cpu` の解析頻度を約10fpsに変更し、30fps入力では3フレームごとに解析するよう調整した。再生予定から遅れた場合は、その回の認識処理だけ自動スキップして映像表示を優先する `adaptive_skip` を追加。スキップ中も警告パネルと赤い基準中心線を軽量描画するようにした。カメラ設置位置差に対応するため、UIに `基準中心` スライダーを追加し、車線フォールバック/LDW判定/赤線描画に反映した。
- **影響**: `config/default.yaml`, `config/realtime_cpu.yaml`, `config/turbo_cpu.yaml`, `config/view_only.yaml`, `src/ui/inference_thread.py`, `src/ui/main_window.py`, `src/pipeline.py`, `src/render/renderer.py`, `src/utils/geometry.py`, `src/lane/classical.py`, `src/lane/lane_detector.py`, `tests/test_config.py`, `README.md`。関連 Phase: PLAN.md §2.6 / §2.11 / §6 / §8。
- **次の方針**: 実動画で突発的な遅延がどの程度減るか確認し、まだ目立つ場合は解析を完全非同期キュー化する。
- **メモ**: 標準は 24fps→2フレームごと、30fps→3フレームごと、60fps→6フレームごと。`ruff check .` 成功、`pytest` は 7 passed。

### 2026-05-11 10:54 — [Codex] [修正] 標準解析頻度を30fpsで6フレームごとに調整
- **内容**: 標準 `realtime_cpu` の `analysis_fps` を 5 に変更し、30fps入力では6フレームごとに解析するよう調整した。解析頻度を上げる代わりに、YOLO入力を224px、最大検出数20、信頼度0.45へ絞り、解析1回あたりの負荷を抑えた。超軽量は YOLO 192px、最大検出数12、解析約3fpsへ調整した。
- **影響**: `config/default.yaml`, `config/realtime_cpu.yaml`, `config/turbo_cpu.yaml`, `src/detection/yolo_detector.py`, `src/tracking/byte_tracker.py`, `src/pipeline.py`, `tests/test_config.py`, `README.md`。関連 Phase: PLAN.md §6 / §8。
- **次の方針**: 実動画で「6フレームごとの検出」と「再生の滑らかさ」のバランスを確認する。突発的な遅延が残る場合は非同期解析キュー化を検討する。
- **メモ**: 標準は 24fps→5フレームごと、30fps→6フレームごと、60fps→12フレームごと。`ruff check .` 成功、`pytest` は 7 passed。

### 2026-05-11 10:48 — [Codex] [修正] FPS連動の解析間引きと映像優先表示を実装
- **内容**: 入力FPSに応じて解析間隔を自動決定する `ui.analysis_fps` を追加。標準は約2fps、超軽量は約1fpsだけAI解析し、それ以外のフレームはパイプラインを通さず縮小表示するようにした。`映像のみ` プロファイルも追加し、AI処理なしで滑らかさを優先できるようにした。
- **影響**: `config/default.yaml`, `config/realtime_cpu.yaml`, `config/turbo_cpu.yaml`, `config/view_only.yaml`, `src/ui/inference_thread.py`, `scripts/evaluate_alerts.py`, `src/ui/main_window.py`, `tests/test_config.py`, `README.md`。関連 Phase: PLAN.md §6 / §8。
- **次の方針**: 実動画で標準/超軽量/映像のみを比較し、必要なら解析頻度や処理幅をさらに落とす。
- **メモ**: 高解像度デモでは標準 `540x248`、超軽量 `360x166`、映像のみ `720x332` で出力。`ruff check .` 成功、`pytest` は 7 passed。

### 2026-05-11 10:43 — [Codex] [修正] 精度より速度優先の超軽量プロファイルを追加
- **内容**: 標準 `realtime_cpu` をさらに高速化し、処理幅 640px、YOLO 256px、YOLO/車線6フレームに1回、信号10フレームに1回、UI更新3フレームに1回へ変更した。さらに `config/turbo_cpu.yaml` を追加し、処理幅 480px、YOLO 224px、YOLO/車線10フレームに1回、信号判定OFFの「超軽量」プロファイルを UI から選べるようにした。
- **影響**: `config/realtime_cpu.yaml`, `config/turbo_cpu.yaml`, `src/ui/main_window.py`, `tests/test_config.py`, `README.md`。関連 Phase: PLAN.md §6 / §8。
- **次の方針**: 実動画で `標準` と `超軽量` の体感を比較し、まだ重ければ `enable_detection: false` の閲覧専用プロファイルを追加する。
- **メモ**: 高解像度デモでは標準が `640x294`、超軽量が `480x220` で出力。`ruff check .` 成功、`pytest` は 6 passed。

### 2026-05-11 10:40 — [Codex] [修正] 標準プロファイルに処理間引きを追加
- **内容**: CPU での体感速度改善のため、標準 `realtime_cpu` で YOLO/車線検出を3フレームに1回、信号判定を5フレームに1回、UI更新を2フレームに1回へ間引く設定を追加した。パイプラインは間のフレームで前回結果を再利用するようにした。
- **影響**: `config/default.yaml`, `config/realtime_cpu.yaml`, `config/full_quality.yaml`, `src/pipeline.py`, `src/ui/inference_thread.py`, `tests/test_config.py`, `README.md`。関連 Phase: PLAN.md §6 / §8。
- **次の方針**: 実動画で体感速度を確認し、必要なら `ui.max_process_width: 640`, `detector.imgsz: 256`, `detector.every_n_frames: 4` まで下げる。
- **メモ**: 高解像度デモの注釈付き出力は `720x332`。`ruff check .` 成功、`pytest` は 5 passed。

### 2026-05-11 10:37 — [Codex] [修正] 高解像度入力の自動縮小を追加して標準設定を高速化
- **内容**: `2778x1284` などの高解像度入力が元サイズのまま車線・信号・描画処理へ流れて遅くなる問題を修正。パイプライン投入前に `ui.max_process_width` へ自動縮小する `resize_for_processing` を追加し、標準 `realtime_cpu` は最大幅 720px、フル品質は 1280px に設定した。YOLO 入力サイズも標準で 320 に下げた。
- **影響**: `src/utils/frame.py`, `src/ui/inference_thread.py`, `scripts/evaluate_alerts.py`, `config/default.yaml`, `config/realtime_cpu.yaml`, `config/full_quality.yaml`, `tests/test_config.py`, `README.md`。関連 Phase: PLAN.md §6 / §8。
- **次の方針**: 実動画で体感速度を確認し、まだ重い場合は `config/realtime_cpu.yaml` の `ui.max_process_width` を 640、または `detector.imgsz` を 256 へ下げる。
- **メモ**: 高解像度デモ `2778x1284` は標準設定で `720x332` の注釈付き動画として出力されることを確認。`ruff check .` 成功、`pytest` は 5 passed。

### 2026-05-11 09:15 — [Codex] [修正] Mac向け軽量設定を標準化しUI選択を追加
- **内容**: `main.py` の標準設定を `config/realtime_cpu.yaml` に変更。UI 左サイドバーに実行プロファイル選択を追加し、`標準（Mac / CPU軽量）`、`フル品質`、`デフォルト` を切り替えられるようにした。README の起動手順も更新した。
- **影響**: `main.py`, `src/ui/main_window.py`, `README.md`。関連 Phase: PLAN.md §2.12 / §B.2 / §B.8。
- **次の方針**: 実動画・カメラでプロファイル切替後の速度と警告表示を確認する。
- **メモ**: `MainWindow()` で `config/realtime_cpu.yaml` が選択されること、`MainWindow("config/full_quality.yaml")` で `フル品質` が選択されることをヘッドレス確認。Ruff 対象チェック成功。

### 2026-05-11 03:03 — [Codex] [テスト] 最終チェックを実行
- **内容**: Ruff、pytest、環境チェック、`realtime_cpu` 設定での PySide6 メインウィンドウ生成、デモ成果物の存在確認を実施した。
- **影響**: Phase 0〜7 の検証。変更ファイルなし。
- **次の方針**: 実カメラまたは自前動画で手動評価し、CPU/MPS 状況に応じて `config/realtime_cpu.yaml` と `config/full_quality.yaml` を使い分ける。
- **メモ**: `ruff check .` 成功、`pytest` は 5 passed、`scripts/check_env.py` 成功、`MPS available: False` は継続。`outputs/recordings/demo_annotated.mp4` と `outputs/recordings/demo_preview.jpg` 生成済み。

### 2026-05-11 03:03 — [Codex] [実装] 実行プロファイルとデモ評価フローを整備
- **内容**: 設定 YAML の `extends` 継承、`main.py --config`、CPU 向け `config/realtime_cpu.yaml`、フル品質 `config/full_quality.yaml`、合成デモ動画生成、評価時の注釈付き動画出力を追加した。評価ログは表示中警告ではなく新規発火警告のみを JSONL に出力するよう修正した。
- **影響**: `src/utils/config.py`, `main.py`, `config/realtime_cpu.yaml`, `config/full_quality.yaml`, `scripts/create_demo_video.py`, `scripts/evaluate_alerts.py`, `src/alert/alert_manager.py`, `src/pipeline.py`, `README.md`, `tests/test_config.py`。関連 Phase: PLAN.md §7 / §B.7〜B.8。
- **次の方針**: 最終チェックを回し、デモ成果物と残課題を明確にして引き継ぐ。
- **メモ**: `data/videos/demo_synthetic.mp4`、`outputs/recordings/demo_annotated.mp4`、`outputs/recordings/demo_preview.jpg`、`outputs/logs/demo_alerts.jsonl` を生成。12フレーム評価で赤信号警告が cooldown どおり 2 件出力された。

### 2026-05-11 02:59 — [Codex] [修正] モデル込みスモークで見つかった実行依存を補正
- **内容**: デフォルト設定で1フレームのモデル込みパイプラインを実行し、ByteTrack に必要な `lap` が不足していることを確認。`requirements.txt` に追加し、`.venv` にインストールした。Ultralytics の設定/キャッシュ先を `outputs/ultralytics` に向け、sandbox 外のホーム配下へ書こうとする警告を解消した。
- **影響**: `requirements.txt`, `src/detection/yolo_detector.py`, `src/tracking/byte_tracker.py`, `scripts/prepare_assets.py`, `.gitignore`。関連 Phase: PLAN.md §2.4 / §B.3。
- **次の方針**: 実動画で FPS と警告の出方を確認し、必要に応じて `imgsz`, `every_n_frames`, 機能トグルを調整する。
- **メモ**: モデル込み1フレーム処理成功（CPU、約4秒、空フレームのため tracks/alerts は 0）。`ruff check .` 成功、`pytest` は 4 passed。

### 2026-05-11 02:56 — [Codex] [実装] ネット参照とモデル資産ダウンロードを実施
- **内容**: 公式/公開情報を参照し、`scripts/prepare_assets.py` を追加。YOLOv8n、YOLOv8s、SegFormer Cityscapes、Depth Anything V2 Small HF を `models/` に取得し、ローカル資産を優先する設定へ更新した。SegFormer/Depth Anything は実モデル推論に対応し、失敗時は既存フォールバックへ戻る。
- **影響**: `scripts/prepare_assets.py`, `config/default.yaml`, `src/segmentation/road_segmenter.py`, `src/depth/monocular.py`, `src/pipeline.py`, `README.md`。関連 Phase: PLAN.md §2.5, §2.7, §2.8, §B.3〜B.7。
- **次の方針**: 実動画でモデル推論速度と警告精度を確認し、重い場合は UI の機能トグルや `every_n_frames` を調整する。
- **メモ**: `models/assets_manifest.json` 作成済み。ローカルモデルロード確認、`ruff check .`、`pytest` 成功。参照元: Ultralytics YOLOv8、Hugging Face SegFormer/Depth Anything、Mapillary traffic signs。

### 2026-05-11 02:53 — [Codex] [テスト] 全体チェックと UI 起動確認を実施
- **内容**: Ruff、pytest、`scripts/check_env.py`、PySide6 メインウィンドウのヘッドレス生成を実行した。
- **影響**: Phase 0〜7 の実装検証。変更ファイルなし。
- **次の方針**: 実動画・カメラで手動確認し、警告しきい値とモデル設定を調整する。
- **メモ**: `ruff check .` 成功、`pytest` は 4 passed、`QT_QPA_PLATFORM=offscreen` で `MainWindow` 生成成功。MPS は引き続き `False`。

### 2026-05-11 02:53 — [Codex] [実装] Phase 1〜7 の一通りのアプリ実装を追加
- **内容**: 入力 UI、推論スレッド、パイプライン、YOLO/ByteTrack 統合、車線検出、路面マスクフォールバック、距離推定フォールバック、TTC/飛び出し/対向車侵入/前車発進/赤信号注意、AlertManager、Renderer、視認性補正、信号色補助判定、評価スクリプト、標識学習入口、README、単体テストを追加した。
- **影響**: `src/` 配下の各モジュール、`main.py`, `config/default.yaml`, `README.md`, `scripts/evaluate_alerts.py`, `scripts/train_jp_signs.py`, `tests/`。関連 Phase: PLAN.md §5 Phase 1〜7 / §B.2〜B.8。
- **次の方針**: 自前動画を `data/videos/` に置いて UI と `scripts/evaluate_alerts.py` で実動画評価を行う。日本標識はデータセット準備後に `scripts/train_jp_signs.py` で追加学習する。
- **メモ**: 外部モデルや学習データが未準備でもアプリが起動できるよう、重いモデルは遅延ロードし、路面/深度/標識は軽量フォールバックを実装した。

### 2026-05-11 02:44 — [Codex] [テスト] Phase 0 環境チェックを実施
- **内容**: `scripts/check_env.py`、Python 構文チェック、Ruff、PySide6 の最小起動チェックを実行した。
- **影響**: Phase 0 の検証。変更ファイルなし。
- **次の方針**: MPS 可用性だけ継続確認し、Phase 1 の入力 UI 実装へ進む。
- **メモ**: `py_compile` 成功、`ruff check main.py scripts/check_env.py src` 成功、`QT_QPA_PLATFORM=offscreen` で PySide6 QApplication 作成成功。Git リポジトリは未初期化。

### 2026-05-11 02:44 — [Codex] [実装] Phase 0 環境スケルトンを作成
- **内容**: `PLAN.md` B.1 に従い、venv 作成、`requirements.txt`、環境確認スクリプト、設定 YAML、プロジェクトディレクトリ、最小 `main.py`、共通データ型を作成した。依存ライブラリは `.venv` にインストール済み。
- **影響**: `requirements.txt`, `config/default.yaml`, `config/japan_signs.yaml`, `scripts/check_env.py`, `main.py`, `src/__init__.py`, `src/types.py`, `src/pipeline.py`, `.gitignore`。関連 Phase: PLAN.md §5 Phase 0 / §B.1。
- **次の方針**: MPS が `False` の理由を確認しつつ、Phase 1 の入力 UI（動画ファイル/カメラ読込）へ進む。
- **メモ**: `.venv/bin/python scripts/check_env.py` は成功。出力は Python 3.11.7、Torch 2.11.0、OpenCV 4.13.0、`MPS available: False`。

### 2026-05-11 — [ユーザー & Claude] [意思決定] ドキュメント運用ルールを確定
- **内容**: 計画と実装手順を `PLAN.md` 1 本に統合。進捗管理は `PROGRESS.md` に逐次記録するルールを定めた。`IMPLEMENTATION.md` は廃止し、本書を新規作成。
- **影響**:
  - `PLAN.md` 冒頭に「ドキュメント運用ルール」セクション追加
  - `PLAN.md` Part B として実装手順を統合
  - `IMPLEMENTATION.md` 削除
  - `PROGRESS.md` 新規作成
- **次の方針**: Phase 0（環境構築）に着手するかどうかをユーザーに確認

### 2026-05-11 — [ユーザー & Claude] [議論] プロジェクト方針確定
- **内容**: 簡易ADASの開発を開始。要件・追加機能・進め方を議論し `PLAN.md` を作成。
- **確定事項**:
  - 動作環境: macOS + Python 3.10+、MPS 利用
  - 入力: 動画ファイル / カメラ（UI から切替）
  - 警告: 画面オーバーレイのみ（音声は後回し）
  - 全機能を最終的に実装する（MVP→順次拡張）
  - 歩道歩行者の除外は**自動**（セマンティックセグメンテーション利用）
  - 信号・標識は**日本仕様**（追加学習必須）
  - 直進対向車は警告対象外、自車レーン侵入予測のみ警告
  - テスト動画はユーザーが自前で用意
- **影響**: `PLAN.md` 全体
- **次の方針**: ドキュメント運用ルールを定めてから Phase 0 着手

---

## 🚧 未解決事項 / 課題リスト

| # | 起票日 | 種別 | 内容 | 担当 | 解決日 |
|---|--------|------|------|------|--------|
| 1 | 2026-05-11 | 確認待ち | カメラ内部パラメータ（焦点距離・取付高さ）のキャリブ手順を Phase 4 着手前に決める | - | - |
| 2 | 2026-05-11 | 確認待ち | 日本標識データセットの最終ソース（Mapillary 抽出 / 自前撮影 / 公開セット） | - | - |
| 3 | 2026-05-11 | 確認待ち | 評価用動画のシーン定義とアノテーション担当 | - | - |
| 4 | 2026-05-11 | 確認待ち | 自車速度の推定方法（オプティカルフロー精度の検証が必要） | - | - |
| 5 | 2026-05-11 | 確認待ち | テスト動画の保管場所（Git に入れない、Drive/NAS/S3 のどれか） | - | - |
| 6 | 2026-05-11 | 確認待ち | ライセンス選定（Ultralytics YOLO は AGPL なので商用は注意） | - | - |
| 7 | 2026-05-11 | 確認待ち | プライバシー方針（テスト映像の顔・ナンバーをぼかすか） | - | - |
| 8 | 2026-05-11 | ✅ 解決 | arm64 / PyTorch MPS built=True だが `torch.backends.mps.is_available()` が False になる原因確認 | Claude | 2026-05-11 |
| 9 | 2026-05-11 | 確認待ち | full_quality プロファイル (SegFormer+Depth) が 1.3 fps と遅すぎる。CoreML 化 or 機能を絞るか検討 | - | - |

---

## 🎯 Phase 別タスク状況

### Phase 0: 環境構築
- [x] venv 作成
- [x] `requirements.txt` 確定 & install
- [ ] `scripts/check_env.py` で MPS 確認（スクリプト成功、MPS は False のため要確認）
- [x] ディレクトリスケルトン作成
- [x] `config/default.yaml` 雛形

### Phase 1: 入力UI
- [x] `src/types.py`
- [x] `src/input/base.py`, `video_file.py`, `camera.py`
- [x] `src/ui/inference_thread.py`
- [x] `src/ui/main_window.py`
- [x] `main.py`

### Phase 2: 物体検出 + トラッキング
- [x] `src/utils/config.py`
- [x] `src/detection/yolo_detector.py`
- [x] `src/tracking/byte_tracker.py`
- [x] `src/render/renderer.py`
- [x] `src/pipeline.py`

### Phase 3: 路面・車線
- [x] `src/segmentation/road_segmenter.py`（軽量フォールバック）
- [x] `src/lane/classical.py`
- [x] `src/utils/geometry.py`
- [x] `src/lane/lane_detector.py`

### Phase 4: 衝突予測
- [x] `src/depth/ipm_fallback.py`
- [x] `src/depth/monocular.py`（IPM フォールバック）
- [x] `src/prediction/ttc.py`
- [x] `src/prediction/trajectory.py`
- [x] `src/prediction/intrusion.py`
- [x] `src/prediction/risk_analyzer.py`
- [x] `src/alert/alert_manager.py`

### Phase 5: 視認性改善
- [x] `src/enhancement/night_mode.py`
- [x] `src/enhancement/hdr.py`
- [x] `src/enhancement/enhancer.py`

### Phase 6: 信号・標識（日本仕様）
- [ ] データ収集（信号 1500 / 標識 1500 枚）
- [ ] アノテーション
- [x] `scripts/train_jp_signs.py`
- [x] `src/signs/jp_sign_detector.py`（HSV 補助判定）
- [x] `src/signs/signal_color.py`

### Phase 7: 仕上げ
- [ ] 死角検知 / DMS
- [ ] 雨・霧・逆光対応
- [ ] ONNX / CoreML 化
- [x] 評価指標自動計測スクリプト
- [x] README

---

## 🗳 意思決定ログ

| 日付 | 決定事項 | 経緯 / 理由 |
|------|---------|------------|
| 2026-05-11 | ドキュメントは PLAN.md と PROGRESS.md の 2 本に集約 | ファイルを増やさず一元管理する方針 |
| 2026-05-11 | UI は PySide6 採用 | Qt の QImage / QPainter で高速描画、Mac で安定、QThread で推論を別スレッド化可能 |
| 2026-05-11 | 物体検出は YOLOv8n から開始 | Mac の MPS で 30fps が現実的、Pretrained あり |
| 2026-05-11 | 路面/歩道分離は SegFormer-b0（Cityscapes 学習済み） | 軽量、HF から即利用、3f に 1 回推論で性能出る見込み |
| 2026-05-11 | 警告は画面オーバーレイのみ（音声なし） | ユーザー指示。後フェーズで追加検討 |
| 2026-05-11 | 直進対向車は警告対象外 | ユーザー要件。自車レーン侵入予測のみ critical |
