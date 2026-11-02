# 簡易ADAS（先進運転支援システム）開発計画書

> 本書は実装担当エンジニアが参照する**唯一の設計・実装ガイド**である。
> 概念・要件・設計・アルゴリズム・閾値・関数シグネチャ・受け入れ基準・実装手順をすべて含む。
> 進捗（やったこと／今後の方針）は別ファイル `PROGRESS.md` に逐次記録する（後述ルール参照）。

---

## ⚠ ドキュメント運用ルール（最重要・全員厳守）

本プロジェクトは下記 2 ファイルだけで管理する。**他に作業ドキュメントを増やさない**。

| ファイル | 役割 | 更新タイミング |
|---------|------|---------------|
| `PLAN.md`（本書） | 計画・設計・実装手順すべて | 仕様変更・設計変更時に編集 |
| `PROGRESS.md` | 進捗ログ（やったこと／今やっていること／次の方針） | **作業のたびに必ず追記** |

### 進捗管理ルール（強制）
1. **実装・編集・修正・調査・議論・意思決定** を行ったら、**その都度 `PROGRESS.md` に追記する**
2. 追記内容は最低限以下を含む：
   - 日時（YYYY-MM-DD HH:MM）
   - 担当者
   - 種別（実装 / 修正 / 調査 / 議論 / 意思決定 / 詰まり）
   - 内容（何をしたか／何が起きたか）
   - 影響（変更ファイル、関連 Phase、関連要件）
   - 次の方針（次に何をやるか）
3. 1 日 1 行ではなく **1 タスク 1 エントリ**（粒度: 1〜2 時間の作業単位）
4. 詰まり・未解決事項は `PROGRESS.md` の「未解決」セクションに残し、解決時に解決日を追記
5. 仕様変更が決まったら `PLAN.md` を更新し、`PROGRESS.md` にも「PLAN.md §X を更新」と記録
6. **エントリの削除は禁止**（誤りは取り消し線＋訂正で残す）

> このルールに違反した PR / コミットはレビュー差し戻し対象とする。

---

## 0. プロジェクト概要

### 0.1 目的
車載カメラ映像（動画ファイル / リアルタイムカメラ）から歩行者・車両・車線・信号・標識を検知し、衝突や逸脱の危険を自動判定して画面上に警告表示する簡易ADASを構築する。

### 0.2 動作環境
| 項目 | 内容 |
|------|------|
| OS | macOS 13+（Apple Silicon / Intel 両対応） |
| 言語 | Python 3.10 以上（3.11 推奨） |
| GPU | Apple Silicon は MPS、Intel は CPU フォールバック |
| 入力 | 動画ファイル（mp4/mov/avi） / 内蔵・USBカメラ |
| 出力 | UI上の映像オーバーレイ + イベントログ（CSV/JSON） |

### 0.3 設計原則
1. **モジュール疎結合**: 各機能（検出/トラッキング/予測/警告）は独立したクラスに切り、`Frame` データ構造を介して受け渡し
2. **すべて自動判定**: 手動マスクや手動領域指定は禁止。座標は毎フレーム自動算出
3. **後方互換**: 同一コードベースで動画ファイルもライブカメラも動かせる
4. **段階的有効化**: 各機能を UI トグルで個別に ON/OFF できる
5. **再現性**: 同じ入力で同じ結果（モデル seed 固定、フレーム単位処理）

---

## 1. システム全体アーキテクチャ

### 1.1 データフロー

```
[InputSource]
    │ raw frame (BGR, H×W×3, uint8)
    ▼
[FrameEnhancer]               ← HDR / 夜間補正
    │ enhanced frame
    ▼
[Detector (YOLO)]             ← 物体検出
    │ Detections[]
    ▼
[Tracker (ByteTrack)]         ← ID付与・速度推定
    │ TrackedObjects[]
    ▼
[Segmenter] ────────┐         ← 路面/歩道セグメンテーション
[LaneDetector] ─────┤         ← 車線検出
[DepthEstimator] ───┤         ← 距離推定
[TrafficSignDetector]┤        ← 信号・標識
                    ▼
              [SceneContext]   ← フレームの全認識結果を保持
                    │
                    ▼
            [RiskAnalyzer]     ← TTC・侵入・飛び出し判定
                    │ Alerts[]
                    ▼
            [AlertManager]     ← 警告の優先度制御・抑制
                    │
                    ▼
              [Renderer]       ← オーバーレイ描画
                    │
                    ▼
                  [UI]
```

### 1.2 共通データ構造（`src/types.py`）

```python
@dataclass
class Detection:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    cls: str                                  # "person", "car", ...
    conf: float                               # 0.0 - 1.0

@dataclass
class TrackedObject:
    track_id: int
    bbox: tuple[float, float, float, float]
    cls: str
    conf: float
    velocity: tuple[float, float]            # px/frame
    history: deque[tuple[float, float]]      # 中心点の履歴 (最大30)
    age: int                                  # 連続観測フレーム数
    distance_m: float | None                 # 推定距離 (None なら未推定)

@dataclass
class LaneInfo:
    left_lane: np.ndarray | None             # ポリライン点列
    right_lane: np.ndarray | None
    ego_lane_polygon: np.ndarray | None      # 自車レーン領域
    vanishing_point: tuple[int, int] | None

@dataclass
class SceneContext:
    frame_idx: int
    timestamp: float
    image: np.ndarray
    enhanced: np.ndarray
    detections: list[Detection]
    tracks: list[TrackedObject]
    road_mask: np.ndarray | None             # 0=その他, 1=車道, 2=歩道
    lanes: LaneInfo
    depth_map: np.ndarray | None             # H×W float32 (m)
    signs: list[Detection]
    signals: list[Detection]

@dataclass
class Alert:
    kind: str            # "collision", "ldw", "front_start", ...
    level: int           # 1=info, 2=warn, 3=critical
    target_id: int | None
    message: str
    bbox: tuple[float, float, float, float] | None
```

---

## 2. モジュール詳細仕様

### 2.1 InputSource（`src/input/`）

#### 責務
動画ファイル/カメラを統一インターフェースで読み出す。

#### インターフェース
```python
class InputSource(Protocol):
    def open(self) -> None: ...
    def read(self) -> tuple[bool, np.ndarray]: ...
    def close(self) -> None: ...
    @property
    def fps(self) -> float: ...
    @property
    def frame_size(self) -> tuple[int, int]: ...
    def seek(self, frame_idx: int) -> bool: ...   # ファイルのみ
```

#### 実装
- `VideoFileSource`: `cv2.VideoCapture(path)` ベース
- `CameraSource`: `cv2.VideoCapture(index)` ベース、デバイス列挙は `AVFoundation` 経由

#### カメラ列挙（macOS）
```python
# 0,1,2... を順に open して成功するものを返す（最大8）
# AVFoundation バックエンド指定: cv2.CAP_AVFOUNDATION
```

---

### 2.2 FrameEnhancer（`src/enhancement/`）

#### 責務
低照度・逆光フレームの視認性を上げ、後段の検出精度を改善する。

#### サブモジュール

##### 2.2.1 NightMode（CLAHE + ガンマ + デノイズ）
- LAB 変換 → L チャネルに `cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))`
- ガンマ補正: γ=0.6（暗部持ち上げ）
- `cv2.fastNlMeansDenoisingColored(h=5, hColor=5)`
- **自動切替条件**: フレーム平均輝度 < 60（0-255）で ON

##### 2.2.2 SoftwareHDR（単一フレーム LDR→HDR 風）
- アプローチA（軽量・既定）: ローカルトーンマッピング = `cv2.detailEnhance` + `bilateralFilter`
- アプローチB（高品質・任意）: 露出ブラケット風＝1フレームから露出±2段の擬似画像を作って `cv2.createMergeMertens` で合成
  - `gamma_high = 0.5`, `gamma_low = 2.0` で擬似多重露光
- **自動切替条件**: 輝度ヒストグラムの両端（<10 と >245）合計が10%超で ON

##### 2.2.3 切替判定
```python
class FrameEnhancer:
    def process(self, frame: np.ndarray) -> np.ndarray:
        if self._is_low_light(frame):
            frame = self._night_mode(frame)
        if self._is_high_contrast(frame):
            frame = self._hdr(frame)
        return frame
```

---

### 2.3 Detector（`src/detection/yolo_detector.py`）

#### 採用モデル
- **既定**: `yolov8n.pt`（速度優先、Mac で 30fps 目標）
- **高精度**: `yolov8m.pt`（任意切替）
- 提供元: Ultralytics、COCO 80クラス事前学習

#### 設定
```python
class YoloDetector:
    def __init__(self,
                 weights: str = "yolov8n.pt",
                 device: str = "mps",          # Apple Silicon
                 conf: float = 0.35,
                 iou: float = 0.5,
                 classes: list[int] = [0,1,2,3,5,7]):  # person,bicycle,car,motorcycle,bus,truck
        ...
    def detect(self, frame: np.ndarray) -> list[Detection]: ...
```

#### 注意点
- MPS 未対応演算が出たら `device="cpu"` フォールバック
- 入力は BGR を内部で RGB に変換
- 推論サイズ: 640（既定）、UI で 416/640/960 切替可能

---

### 2.4 Tracker（`src/tracking/byte_tracker.py`）

#### 採用
- Ultralytics YOLO の `model.track(persist=True, tracker="bytetrack.yaml")` を使用
- 自前 ByteTrack 実装は避け、ライブラリ提供を活用

#### 出力で必ず付与する派生量
| 量 | 算出方法 |
|----|---------|
| `velocity` | 直近5フレームの中心点を最小二乗線形回帰した傾き（px/frame） |
| `history` | `deque(maxlen=30)` に中心点を蓄積 |
| `age` | 連続観測フレーム数 |

#### 喪失時の扱い
- 5 フレーム以上連続で検出されなかった ID は破棄（ByteTrack の `track_buffer` で制御）

---

### 2.5 Segmenter（`src/segmentation/road_segmenter.py`）

#### 目的
歩道上の歩行者を警告から除外するため、車道／歩道／その他を毎フレーム自動分離する。

#### 採用モデル
- **既定**: `nvidia/segformer-b0-finetuned-cityscapes-1024-1024`（HuggingFace）
- 出力 19 クラス → 統合
  - `road`(=7) → 値 1（車道）
  - `sidewalk`(=8) → 値 2（歩道）
  - その他 → 値 0
- **代替（軽量）**: 既存の YOLO に `yolov8n-seg.pt` を併用してインスタンス segmentation で代替検討（精度劣る）

#### 動作頻度
- 毎フレームは重い → **3 フレームに 1 回推論**、間は前回マスクを流用
- 解像度: 入力を 512×512 にリサイズして推論 → 元解像度に戻す

#### インターフェース
```python
class RoadSegmenter:
    def predict(self, frame: np.ndarray) -> np.ndarray:
        # returns H×W uint8 (0=other, 1=road, 2=sidewalk)
        ...
```

#### 歩道歩行者の判定
- 検出された人 BB の **底辺中心点** が `road_mask == 2`（歩道）の領域にあれば警告対象から除外
- 底辺中心が車道(1)、または車道境界5pxバッファ内なら警告対象

---

### 2.6 LaneDetector（`src/lane/lane_detector.py`）

#### Phase 1 実装（軽量・古典手法）
1. ROI（画像下半分）切り出し
2. グレースケール → `cv2.GaussianBlur(5,5)` → `cv2.Canny(50, 150)`
3. `cv2.HoughLinesP(rho=1, theta=π/180, threshold=50, minLineLength=40, maxLineGap=100)`
4. 傾きで左/右に分類（負傾き=左、正傾き=右）
5. 各群の平均線を 1 次関数で当てはめ → ポリライン生成

#### Phase 5 強化（DL 化）
- `cuiluo/Ultra-Fast-Lane-Detection-V2` を移植 or `lanenet` を ONNX 化
- 雨天・夜間で古典手法が破綻するため切替

#### LDW 判定
- 自車中心 X = 画面中央 X
- 左右レーン下端 X との距離が両方とも 30px 未満になったら逸脱
- ヒステリシス: 警告開始は閾値 30px、解除は 50px

#### 消失点
- 左右レーンの直線交点 → 危険ゾーン台形定義に使用

---

### 2.7 DepthEstimator（`src/depth/depth_estimator.py`）

#### 採用モデル
- `depth-anything/Depth-Anything-V2-Small`（HuggingFace）
- 単眼相対深度 → スケールキャリブレーションで絶対距離化

#### スケール推定
- 検出した「車」の BB 高さから経験則で距離初期推定:
  - 一般車の平均車高 1.5m、焦点距離 f（カメラ仕様 or 推定）
  - `distance ≈ (f * real_height) / bbox_height`
- これと相対深度マップの対応点で線形回帰してスケール固定（最初の数十フレームでキャリブ）

#### 計算頻度
- **2 フレームに 1 回**（重い）

#### 簡易フォールバック
- 深度モデルを使わず、**BB 底辺の Y 座標 → 路面ホモグラフィ → 距離** で代替可能
- カメラ取り付け高さ 1.2m、ピッチ角 0° と仮定した IPM（逆透視変換）

---

### 2.8 TrafficSignDetector（`src/signs/`）

#### 必須要件
- **日本仕様の信号・標識を識別する** → 追加学習が確定要件

#### 学習計画（Phase 6）
| 項目 | 内容 |
|------|------|
| クラス例 | 信号: red/yellow/green/arrow_left/arrow_right/arrow_straight、歩行者赤/青、標識: stop, yield, no_entry, speed_30/40/50/60, slow |
| データ収集 | 自前撮影 + 公開データ（東大 / 産総研の公開セット、Mapillary Traffic Sign Dataset から日本データのみ抽出）|
| アノテーション | Roboflow / CVAT、最低 3000 枚 |
| ベースモデル | YOLOv8s（COCO pretrained） + 日本標識でファインチューニング |
| 評価 | mAP@0.5 ≥ 0.7、信号色の混同行列で yellow→red 誤検出率 ≤ 5% |

#### 信号色判定の補助
- 信号BB を切り出し → HSV 空間で赤/黄/緑領域の面積比較で色推定（モデル誤判定の補正）

---

### 2.9 RiskAnalyzer（`src/prediction/risk_analyzer.py`）

#### 入力
`SceneContext`（前後数フレーム保持）

#### 出力
`list[Alert]`

#### 個別ロジック

##### 2.9.1 危険ゾーンの自動定義
- 消失点 V、画面下端の自車レーン左右端 L, R
- 台形 `[L, V±20px (左右), R]` を「直近危険ゾーン」とする
- レーンが取れない場合は画面中央 ±20%、下から 60% を fallback

##### 2.9.2 TTC（衝突時間）計算
- 対象の距離 d（m）と相対速度 v_rel（m/s）から `TTC = d / v_rel`
- v_rel: 過去 N フレームの距離履歴の傾き（線形回帰）
- 警告レベル:
  - `TTC < 1.5s` → critical（赤）
  - `1.5s ≤ TTC < 3.0s` → warn（黄）
  - それ以上 → 無視

##### 2.9.3 歩行者警告
- 条件: 人クラス AND 底辺が車道領域 AND 危険ゾーン内 OR TTC < 3.0s
- **歩道上は除外**

##### 2.9.4 飛び出し検知
- 条件: 人/自転車の `age <= 5` フレーム AND 中心点速度 |v| > 8 px/frame AND ゾーン端から内側へ移動
- 速度ベクトルが画面中央へ向いている場合のみ

##### 2.9.5 対向車の右左折侵入予測
> **大原則**: **直進する対向車は警告対象としない**。自車レーンへ侵入してくる軌跡を示した対向車だけを警告する。

- **対向車の判定**: 進行方向ベクトルが自車進行と逆（画像座標で BB 中心が下方向に移動）かつ自車レーンの外側にいる
- **直進判定（除外条件）**:
  - 軌跡履歴（30フレーム）に直線フィット
  - フィット直線が画像下端で自車レーン内に入らない、または横方向速度成分 |vx| < 2 px/frame → **直進＝除外**
- **侵入判定（警告条件）**:
  - 横方向速度 |vx| ≥ 2 px/frame かつ 軌跡の予測直線が自車レーン台形と交差する
  - 交点までの推定到達時間 < 3.0s → critical
  - 交点があるが到達時間 3.0–5.0s → warn
- **追加保険**: 対向車の向き（YOLO の角度推定 or BB アスペクト比変化）が「自車側を向きつつある」（横長 → 縦長へ変化）なら警告レベルを 1 段上げる

##### 2.9.6 前車発進検知
- 前車（自車レーン内 + 最近距離）の速度が
  `直近5フレームほぼ0` → `現フレーム > 2 px/frame` に遷移したら 1.5 秒間 info 表示

##### 2.9.7 車間距離警告
- 推奨車間 = 速度 v(km/h) × 0.3 ÷ 3.6（簡易: 0.6 秒車間 + 反応時間）
- 自車速度は GPS 無しなのでオプティカルフローから推定（路面領域の平均流速 → m/s 換算）
- 距離 < 推奨車間 × 0.7 で warn

##### 2.9.8 LDW
- 2.6 節に記載

##### 2.9.9 信号見落とし
- 信号 BB が画面上半分に存在 AND 色 == 赤 AND 自車速度 > 5 km/h → warn
- 通過後（信号が画面外）に自車が止まっていなければ critical

---

### 2.10 AlertManager（`src/alert/alert_manager.py`）

#### 責務
- 警告の重複抑制（同じ track_id の同種警告は連続で出さない）
- 優先順位付け（critical > warn > info）
- ヒステリシス制御（チャタリング防止）

#### 内部状態
```python
self._last_emit: dict[(track_id, kind), float]  # 最終発火時刻
self._cooldown = {"collision": 0.5, "ldw": 1.0, "front_start": 5.0, ...}
```

---

### 2.11 Renderer（`src/render/renderer.py`）

#### 描画レイヤ（z-order）
1. 元映像（または enhanced）
2. 路面マスク半透明（debug ON 時のみ）
3. 車線ポリライン（緑、太さ 3）
4. 危険ゾーン台形（赤線、α=0.3 塗りつぶし）
5. 検出 BB（クラスごとに色分け）
6. 警告対象 BB（赤太枠 + 点滅、5fpsで明滅）
7. テキストラベル（クラス、ID、距離、TTC）
8. 画面右上の警告サマリーパネル
9. 画面下のステータスバー（FPS、フレーム番号、有効モジュール）

#### 警告サマリーパネル
- 縦並びカード（最大5件）
- 1.0 秒以上更新されない警告は自動消去

---

### 2.12 UI（`src/ui/main_window.py`）

#### フレームワーク
- **PySide6**（採用確定）
- 理由: Qt の QImage / QPainter で高速描画、Mac で安定、QThread で推論を別スレッド化可能

#### 構成
```
┌─────────────────────────────────────────────────────┐
│ メニューバー：File / View / Help                     │
├──────────────┬──────────────────────────────────────┤
│ 入力ソース    │                                       │
│ [▼ ファイル]  │                                       │
│ [選択]        │         映像表示エリア                │
│ ─────────    │      （QLabel + QImage）              │
│ ☑ HDR        │                                       │
│ ☑ 夜間モード  │                                       │
│ ☑ LDW        │                                       │
│ ☑ 衝突予測    │                                       │
│ ☑ 信号認識    │                                       │
│ ☑ 標識認識    │                                       │
│ ─────────    │                                       │
│ 推論サイズ    ├──────────────────────────────────────┤
│ [640 ▼]      │ 警告ログ（QTableView）                │
│              │ time | level | kind | target | msg    │
├──────────────┴──────────────────────────────────────┤
│ ▶ ⏸ ⏹ [シーク==========] 00:01:23 / 00:05:00  30fps │
└─────────────────────────────────────────────────────┘
```

#### スレッド設計
- **UI スレッド**: 描画と入力ハンドリングのみ
- **推論スレッド** (QThread): InputSource → パイプライン → 結果を Signal で UI に送信
- フレームキューは最大 2 枚（古いフレームは捨てる＝リアルタイム優先）

---

## 3. プロジェクト構成（最終）

```
car_program/
├── PLAN.md                  # 本書
├── README.md
├── requirements.txt
├── pyproject.toml           # 任意（uv 使用時）
├── main.py                  # python main.py で起動
├── config/
│   ├── default.yaml         # 全パラメータ集約
│   └── japan_signs.yaml     # 標識クラス定義
├── src/
│   ├── __init__.py
│   ├── types.py             # 1.2 のデータ構造
│   ├── pipeline.py          # 全モジュールを束ねる
│   ├── input/
│   │   ├── base.py
│   │   ├── video_file.py
│   │   └── camera.py
│   ├── enhancement/
│   │   ├── night_mode.py
│   │   ├── hdr.py
│   │   └── enhancer.py
│   ├── detection/
│   │   └── yolo_detector.py
│   ├── tracking/
│   │   └── byte_tracker.py
│   ├── segmentation/
│   │   └── road_segmenter.py
│   ├── lane/
│   │   ├── classical.py
│   │   └── lane_detector.py
│   ├── depth/
│   │   ├── monocular.py
│   │   └── ipm_fallback.py
│   ├── signs/
│   │   ├── jp_sign_detector.py
│   │   └── signal_color.py
│   ├── prediction/
│   │   ├── risk_analyzer.py
│   │   ├── ttc.py
│   │   ├── trajectory.py
│   │   └── intrusion.py
│   ├── alert/
│   │   └── alert_manager.py
│   ├── render/
│   │   └── renderer.py
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── inference_thread.py
│   │   └── widgets/
│   └── utils/
│       ├── geometry.py      # 消失点・台形・幾何計算
│       ├── camera_calib.py
│       └── logger.py
├── models/                  # ダウンロード済み weights
├── data/
│   ├── videos/              # ユーザーが置く動画
│   └── annotations/         # 日本標識アノテーション
├── outputs/
│   ├── logs/
│   └── recordings/
└── tests/
    ├── test_input.py
    ├── test_detector.py
    └── test_risk_analyzer.py
```

---

## 4. 依存ライブラリ（requirements.txt）

```
# 推論
ultralytics>=8.3.0
torch>=2.2.0
torchvision>=0.17.0
transformers>=4.40.0    # SegFormer / Depth Anything
huggingface_hub>=0.23.0

# 画像処理
opencv-python>=4.9.0
numpy>=1.26.0
Pillow>=10.2.0
scikit-image>=0.22.0

# UI
PySide6>=6.6.0

# ユーティリティ
pyyaml>=6.0
loguru>=0.7.0
pandas>=2.2.0           # ログ出力

# 開発
pytest>=8.0.0
ruff>=0.4.0
mypy>=1.10.0
```

> Apple Silicon: `pip install torch torchvision` で MPS 対応版が入る。

---

## 5. Phase 別タスクと完了条件（Definition of Done）

### Phase 0: 環境構築
- [ ] venv 作成: `python3.11 -m venv .venv`
- [ ] requirements.txt 反映、`pip install -r requirements.txt`
- [ ] PyTorch MPS 動作確認スクリプト（`torch.backends.mps.is_available()`）
- [ ] プロジェクトのディレクトリスケルトン作成
- **DoD**: `python main.py` が空ウィンドウを表示する

### Phase 1: 入力UI（最優先・自前動画で動かす）
- [ ] `VideoFileSource` / `CameraSource` 実装
- [ ] PySide6 メインウィンドウ + ファイル選択ダイアログ + カメラデバイス列挙
- [ ] 推論スレッド骨格（読み込み→そのまま表示）
- [ ] 再生・停止・シーク・FPS表示
- **DoD**: 自前動画と内蔵カメラを UI から選んで再生できる

### Phase 2: 物体検出 + トラッキング
- [ ] `YoloDetector` 実装、UI トグル
- [ ] Ultralytics の track API でID付与
- [ ] velocity / history / age を派生量として保持
- [ ] BB と ID と速度ベクトル矢印を描画
- **DoD**: 動画上で人と車が ID 付きで安定追跡される（Mac で 20fps 以上）

### Phase 3: 路面・車線
- [ ] SegFormer 統合、3 フレームに 1 回推論
- [ ] 古典手法車線検出（Hough）+ LaneInfo 構築
- [ ] 危険ゾーン自動定義
- [ ] LDW ロジック + ヒステリシス
- **DoD**:
  - 歩道に立つ人がBBは出るが**警告対象外**になる
  - 車線をまたぐと LDW 警告が出る

### Phase 4: 衝突予測ロジック
- [ ] DepthEstimator（IPM フォールバックを先に実装）
- [ ] TTC 計算
- [ ] 飛び出し検知
- [ ] 対向車軌跡予測
- [ ] 前車発進 / 車間距離
- [ ] AlertManager の優先度・抑制
- **DoD**: 自前動画の各シーンで期待される警告が出る（手動評価で 80% 以上）

### Phase 5: 視認性改善
- [ ] NightMode（CLAHE+ガンマ+デノイズ）
- [ ] SoftwareHDR（Mertens 擬似多重露光）
- [ ] 自動切替条件の実装
- **DoD**: 夜間動画で検出 mAP が補正なしより 10% 以上向上

### Phase 6: 信号・標識（日本仕様）
- [ ] 自前動画 / 公開データから日本の信号・標識を 3000 枚以上収集
- [ ] CVAT または Roboflow でアノテーション
- [ ] YOLOv8s ファインチューニング（学習スクリプト + 評価レポート）
- [ ] 信号色 HSV 補正
- [ ] 信号見落とし警告ロジック
- **DoD**: 自前動画で日本の信号・標識を mAP@0.5 ≥ 0.7 で検出

### Phase 7: 死角検知 / DMS / 環境対応 / 最適化
- [ ] 死角検知（側方カメラ前提、後回し）
- [ ] DMS（別カメラ前提、後回し）
- [ ] CoreML / ONNX 化で 30fps 安定
- [ ] 評価指標自動計測スクリプト
- **DoD**: 全機能ON で 720p / 25fps 以上を Mac で維持

---

## 6. パフォーマンス目標

| 機能組合せ | 解像度 | 目標FPS | Mac M1 想定 |
|----------|--------|---------|-------------|
| 検出のみ | 720p | 30 | YOLOv8n / MPS |
| 検出+追跡+セグ | 720p | 20 | セグは3fに1回 |
| 全機能ON | 720p | 15 | 深度2fに1回、信号2fに1回 |

---

## 7. テスト戦略

### 7.1 単体テスト（pytest）
- 幾何計算、TTC、AlertManager の状態遷移、入力ソースのモック
- カバレッジ目標: 60% 以上（UI・モデル推論部除く）

### 7.2 統合テスト
- 短い検証用動画（10秒×6本: 昼/夜/前車発進/飛び出し/逸脱/赤信号）を `data/videos/test/` に置き、各シーンで期待される警告が発火するかをスナップショットテスト

### 7.3 評価指標
| 指標 | 算出方法 |
|------|---------|
| 検出 mAP@0.5 | 自前動画にBBアノテーション（最低500枚） |
| 警告適合率 / 再現率 | 各シーンで「正解警告タイミング」を秒単位で人手定義し比較 |
| 誤検知率 | 1分あたりの誤警告回数（目標 < 3回） |
| 見逃し率 | 想定危険シーンで警告が出なかった割合（目標 < 10%） |

---

## 8. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| MPS 未対応演算 | 推論落ちる | `device="cpu"` に動的フォールバック |
| 単眼距離推定の精度不足 | TTC が不正確 | IPM ベースを併用、信頼度の低いものは TTC 出さない |
| 古典車線検出が夜間で破綻 | LDW 出ない | Phase 5 で DL 化に切替 |
| 日本標識データ不足 | 学習進まない | 自前撮影＋データ拡張（コピペ合成、明度・反転） |
| Mac で fps 出ない | リアルタイム性損失 | 推論サイズ縮小、フレームスキップ、ONNX/CoreML 化 |

---

## 9. 設定パラメータ集約（`config/default.yaml` の例）

```yaml
input:
  source_type: file          # file | camera
  path: data/videos/test.mp4
  camera_index: 0

detector:
  weights: yolov8n.pt
  device: mps
  conf: 0.35
  iou: 0.5
  imgsz: 640
  classes: [0,1,2,3,5,7]

tracker:
  type: bytetrack
  track_buffer: 30

segmenter:
  model: nvidia/segformer-b0-finetuned-cityscapes-1024-1024
  every_n_frames: 3
  input_size: 512

depth:
  enabled: true
  model: depth-anything/Depth-Anything-V2-Small
  every_n_frames: 2
  ipm_fallback: true
  cam_height_m: 1.2

lane:
  method: classical          # classical | dl
  ldw_threshold_px: 30
  ldw_release_px: 50

risk:
  ttc_critical_s: 1.5
  ttc_warn_s: 3.0
  follow_distance_factor: 0.7

ui:
  width: 1280
  height: 800
  show_debug_mask: false
```

---

## 10. ロギング / イベント出力

- `outputs/logs/{YYYYMMDD_HHMMSS}.csv`
  - カラム: timestamp, frame_idx, kind, level, target_id, message, bbox
- 起動ごとに新規ファイル
- `loguru` で標準出力 + ファイル両方

---

## 11. 残課題 / 未確定事項

| # | 内容 | 期限 |
|---|------|------|
| 1 | カメラ内部パラメータ（焦点距離・取付高さ）のキャリブ手順 | Phase 4 着手前 |
| 2 | 日本標識データセットの最終ソース選定 | Phase 6 着手前 |
| 3 | 評価用動画のシーン定義（誰がアノテーション付けるか） | Phase 4 着手前 |
| 4 | 自車速度の推定方法（オプティカルフロー精度の検証） | Phase 4 中盤 |

---

## 12. Plan A of 20260712 - 車線精度と低遅延化

### 12.1 方針と非目標

- 物体検出は全画面YOLOを維持する。車線専用の局所ROI最適化を、YOLOの検出範囲には使わない。
- 車線が明瞭に検出できる時だけ、滑らかな車線表示とLDWを有効にする。
- 車線がない道路、低信頼度、または古い推論結果では、擬似台形を車線として扱わず、車線表示とLDWを停止する。
- Rustへの全面移行は行わない。OpenCV、GStreamer、Hailoのネイティブ実装を優先し、Python固有ループが計測上のボトルネックだった場合だけ再検討する。

### 12.2 v15 - 計測と採否基盤

1. 実走USBカメラ映像を、晴天、影、逆光、夜、雨、カーブ、破線、白線なし、交差点に分類して保存する。
2. 各動画について、車線検出継続率、横ずれ誤差、LDW誤報/見逃し、撮影から警報までの遅延、各ステージのp50/p95を記録する。
3. カメラ、推論、警報に撮影時刻を持たせ、古いフレームの結果を使った警報を検出する。

**受け入れ基準**: 同一動画・同一設定で、変更前後の精度とp95遅延を自動比較できること。

### 12.3 v16 - CPU車線検出の刷新

1. カメラ校正値から歪み補正とIPM変換表を起動時に生成する。
2. IPM後の車線専用領域で、色・勾配マスク、下端ヒストグラム、スライディングウィンドウにより左右の候補画素を得る。
3. 左右それぞれをRANSAC二次曲線 `x=f(y)` で推定し、車線幅、曲率、消失点、インライア率から信頼度を算出する。
4. 曲線係数を信頼度付きKalman Filterで追跡する。`TRACK`中は予測曲線周辺のみを探索し、`LOST`時だけ全域探索へ戻る。
5. 車線状態を `SEARCH`、`ACQUIRE`、`TRACK`、`LOST` に分ける。LDWは短時間の連続高信頼度確認後だけ有効にし、`LOST`では即時停止する。

**期待効果**: Hough直線と固定フレーム平均より、カーブ、破線、部分遮蔽への追従性を上げる。局所追跡により通常フレームの全域探索を避け、精度を保ったまま車線処理時間を下げる。

### 12.4 v18 - Hailo車線AIの条件付き導入

1. v16が夜間、逆光、白線消失、分岐で目標を満たさない場合だけ、Hailo変換可能な軽量車線AIを候補化する。
2. 実走映像を代表データとしてINT8量子化し、変換前後の車線精度と遅延を比較する。
3. 車線AIの結果は撮影時刻付きで受け取り、鮮度上限を超えた結果はLDWに使わない。
4. 高信頼度AI結果は優先し、AIが低信頼度ならv16の古典IPM方式を使う。両方低信頼度なら車線なしとして扱う。
5. 車線AIは10-15Hz以上を目標とし、間のフレームはv16の曲線追跡で補完する。

**採用条件**: Hailo変換後の実走精度がv16を上回り、撮影から車線結果までのp95遅延がv16の許容値内であること。NPU推論が速くても、入力変換、転送、キュー滞留を含む総遅延が悪化するなら採用しない。

### 12.5 横断的な高速化

| 施策 | 実施内容 | 効果の判定 |
|---|---|---|
| 固定小数点IPM | `cv2.convertMaps`でIPM変換表を固定小数点化 | `remap`のp95を比較。OpenCVは高速化の可能性を示すが、全体速度とは分けて評価する。 |
| 粗探索から精密化 | 低解像度BEVで候補を発見し、候補帯だけ高解像度で曲線を再推定 | 横ずれ誤差を悪化させずにlane stageのp95を削減できるか確認する。 |
| 適応前処理 | 明るさ・コントラストが安定時はCLAHEや強いモルフォロジーを省略 | 明暗条件別に検出率を落とさず前処理時間を削減できるか確認する。 |
| 最新1フレーム | GStreamer/V4L2入力、Hailo、危険判定の各キューを1フレームに制限する | FPSではなく、撮影から警報までのp95遅延と古い結果の利用ゼロで評価する。 |
| 多レート実行 | YOLO/Hailo、車線、危険判定、描画を同一頻度に固定しない | 危険判定20-30Hzを維持しつつ、CPU/NPU使用率とp95を確認する。 |

OpenCVの`convertMaps`、GStreamerの`appsink`、Hailoの導入は、それぞれの公式資料を参照する。性能値はハードウェア・カメラ・モデルに依存するため、v15の実測を採否の唯一の根拠とする。

### 12.6 実装状態（2026-07-12）

- **v15完了**: `scripts/profile_pipeline.py` にwarmup除外と車線状態集計を追加し、`scripts/evaluate_lanes.py` で注釈付き実走動画の車線検出率と自車レーン中心誤差を記録できるようにした。
- **v16完了**: `src/lane/ipm.py` に固定小数点IPM、粗探索/局所追跡、ロバスト曲線当てはめ、曲線係数Kalman Filterを実装した。IPMモードでは車線未検出時に擬似車線やLDWを出さない。
- **v18準備完了**: カメラ撮影時刻、車線結果の鮮度上限、最新フレーム処理、古い車線結果の描画/LDW抑制を実装した。
- **v18実機受け入れ試験は保留**: Pi 5 + AI HAT実機、Hailo変換可能な車線モデル、実走キャリブレーション映像が必要であり、このMac環境では実行できない。Hailo導入は、v16との精度・p95遅延比較を満たした場合だけ採用する。
- **車線検出の堅牢化（2026-07-12）**: 薄い白線に適応するしきい値、車両BBのマスク、左右幅・画面中心・時間変化の妥当性検査を追加した。候補が不自然ならKalman更新前に棄却し、複数車線幅に相当する逸脱率はLDWとして表示しない。
- **台形参照の統合（2026-07-12）**: ユーザー調整済みの赤い台形を、車線候補の探索ピークと信頼度に使うソフトな事前情報として接続した。YOLOの全画面検出は制限せず、台形から大きく外れた候補だけを低信頼度/棄却とする。

### 12.7 カスタム2の多レート処理とYOLOX Tiny追跡安定化

- 車線検出とYOLO検出は独立周期・位相でスケジュールする。カスタム2は車線 `phase=0`、YOLO `phase=1` とし、6フレーム周期の処理を別フレームへ分散する。
- 同一フレームに重なった場合はYOLOを優先し、車線検出を次の非YOLOフレームへ延期する。検出済みの車両結果と車線結果はそれぞれの最新結果を保持する。
- YOLOX Tinyの速度は検出フレーム間隔ではなく実フレーム番号差で計算する。対応付けはクラス、予測中心、IoU、BB面積変化でゲートし、不自然なジャンプは新IDにする。
- 新規外部トラックは2回の整合検出まで軌跡依存の危険判定へ通さない。歩行者・自転車の自車レーン内0.25秒警告は維持する。
- 物体相対速度の自車補正は対象近傍の実測フローだけを使い、画面全体の横フローを使わない。車両の侵入警告は近距離・画面下・2フレーム連続条件を満たす場合に限定する。
- 危険対象はBB下端の中心を、同じ奥行きでの自車レーン/走行台形の幅と比較して `左`・`中央`・`右` に分類する。中央帯は進路幅の30%として、検出揺れによる左右の頻繁な反転を抑える。

**受け入れ基準**: カスタム2でlane/detectorの実行フレームが重ならないこと、検出間隔6で12px/6フレームの移動が約2px/frameとして扱われること、数百pxのジャンプでIDを引き継がないこと、未確認トラックが車両侵入警告を出さないことを自動テストする。

---

## 次のアクション
- [x] 計画書の詳細化（本書）
- [x] 計画と実装手順を本書に統合
- [x] 進捗管理ルールを定義（`PROGRESS.md`）
- [ ] Phase 0 開始（venv + requirements.txt + ディレクトリ作成）
- [ ] Phase 1: 入力ソース選択 UI を最優先実装

---

# Part B: 実装手順書

> ここから先は **上から順に手を動かせば動くものができる** ステップを記述する。
> 各ステップは「作るファイル」「実装内容」「動作確認」「コミット粒度」をセットで持つ。

---

## B.0 開始前の準備

### B.0.1 必要ツール
- Python 3.10 以上（推奨 3.11）
- Git
- VSCode または PyCharm
- macOS 13 以上

### B.0.2 リポジトリ初期化
```bash
cd /Users/tyakyumyou/Downloads/car_program
git init
cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
models/
outputs/
data/videos/*.mp4
data/videos/*.mov
.DS_Store
EOF
git add PLAN.md PROGRESS.md .gitignore
git commit -m "init: planning and progress documents"
```

---

## B.1 Phase 0: 環境構築（所要 0.5 日）

### Step 0-1: venv 作成
```bash
cd /Users/tyakyumyou/Downloads/car_program
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### Step 0-2: requirements.txt
`requirements.txt`（§4 と同じ内容）を作成し `pip install -r requirements.txt`。

### Step 0-3: MPS 動作確認
`scripts/check_env.py`:
```python
import torch, cv2, sys
print("Python:", sys.version)
print("Torch:", torch.__version__)
print("MPS available:", torch.backends.mps.is_available())
print("OpenCV:", cv2.__version__)
```
**期待出力**: `MPS available: True`（Apple Silicon の場合）

### Step 0-4: ディレクトリスケルトン
```bash
mkdir -p src/{input,enhancement,detection,tracking,segmentation,lane,depth,signs,prediction,alert,render,ui,utils}
mkdir -p config models data/videos outputs/logs tests scripts
touch src/__init__.py src/types.py src/pipeline.py main.py
```

### Step 0-5: 設定ファイル雛形
`config/default.yaml` に §9 の YAML をコピー。

### コミット
```
feat: bootstrap project skeleton (phase 0)
```

### Phase 0 完了条件
- [ ] `python scripts/check_env.py` が成功する
- [ ] ディレクトリ構成が §3 と一致
- [ ] `requirements.txt` が固定されている

---

## B.2 Phase 1: 入力UI（最優先・所要 1〜2 日）

> **目標**: 動画ファイルとカメラを UI から選んで再生できる状態。検出ロジックはまだ入れない。

### Step 1-1: 共通データ構造
`src/types.py` に §1.2 の dataclass 定義をすべて記述。

### Step 1-2: 入力ソース基底クラス（`src/input/base.py`）
```python
from typing import Protocol
import numpy as np

class InputSource(Protocol):
    def open(self) -> None: ...
    def read(self) -> tuple[bool, np.ndarray]: ...
    def close(self) -> None: ...
    @property
    def fps(self) -> float: ...
    @property
    def frame_size(self) -> tuple[int, int]: ...
```

### Step 1-3: 動画ファイル入力（`src/input/video_file.py`）
```python
import cv2
import numpy as np

class VideoFileSource:
    def __init__(self, path: str):
        self.path = path
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.path)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open {self.path}")

    def read(self) -> tuple[bool, np.ndarray]:
        return self._cap.read()

    def close(self) -> None:
        if self._cap: self._cap.release()

    @property
    def fps(self) -> float:
        return self._cap.get(cv2.CAP_PROP_FPS) or 30.0

    @property
    def frame_size(self) -> tuple[int, int]:
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return w, h

    def seek(self, frame_idx: int) -> bool:
        return self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
```

### Step 1-4: カメラ入力（`src/input/camera.py`）
```python
import cv2

class CameraSource:
    def __init__(self, index: int = 0):
        self.index = index
        self._cap = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.index, cv2.CAP_AVFOUNDATION)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera {self.index}")

    @staticmethod
    def list_devices(max_index: int = 8) -> list[int]:
        found = []
        for i in range(max_index):
            cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
            if cap.isOpened():
                found.append(i); cap.release()
        return found
```
> **macOS 注意**: 初回カメラアクセスで OS の許可ダイアログが出る。

### Step 1-5: 推論スレッド骨格（`src/ui/inference_thread.py`）
Phase 1 では何もせずフレームを横流し。
```python
from PySide6.QtCore import QThread, Signal
import numpy as np, time

class InferenceThread(QThread):
    frame_ready = Signal(np.ndarray, dict)
    finished_signal = Signal()

    def __init__(self, source):
        super().__init__()
        self.source = source
        self._running = False
        self._paused = False

    def run(self):
        self.source.open()
        self._running = True
        idx = 0; t0 = time.time()
        target_dt = 1.0 / max(self.source.fps, 1.0)
        while self._running:
            if self._paused: self.msleep(20); continue
            ok, frame = self.source.read()
            if not ok: break
            self.frame_ready.emit(frame, {"frame_idx": idx, "fps": self.source.fps})
            idx += 1
            elapsed = time.time() - t0
            sleep = (idx * target_dt) - elapsed
            if sleep > 0: self.msleep(int(sleep * 1000))
        self.source.close()
        self.finished_signal.emit()

    def stop(self): self._running = False
    def pause(self): self._paused = True
    def resume(self): self._paused = False
```

### Step 1-6: メインウィンドウ（`src/ui/main_window.py`）
最小機能：
- メニュー: ファイル → 動画ファイルを開く / カメラを選択
- 中央: QLabel で QImage 表示
- 下部: 再生ボタン、停止ボタン、FPS ラベル

```python
from PySide6.QtWidgets import (QMainWindow, QLabel, QFileDialog, QPushButton,
                               QVBoxLayout, QHBoxLayout, QWidget, QInputDialog)
from PySide6.QtGui import QImage, QPixmap, QAction
from PySide6.QtCore import Qt
import cv2
from src.input.video_file import VideoFileSource
from src.input.camera import CameraSource
from src.ui.inference_thread import InferenceThread

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("簡易ADAS")
        self.resize(1280, 800)
        self.video_label = QLabel("入力ソースを選択してください")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(960, 540)
        self.fps_label = QLabel("FPS: -")
        self.btn_play = QPushButton("▶")
        self.btn_stop = QPushButton("⏹")
        ctrl = QHBoxLayout()
        ctrl.addWidget(self.btn_play); ctrl.addWidget(self.btn_stop); ctrl.addWidget(self.fps_label)
        layout = QVBoxLayout()
        layout.addWidget(self.video_label, 1); layout.addLayout(ctrl)
        w = QWidget(); w.setLayout(layout); self.setCentralWidget(w)
        self._build_menu()
        self.thread: InferenceThread | None = None
        self.btn_play.clicked.connect(self._play_pause)
        self.btn_stop.clicked.connect(self._stop)

    def _build_menu(self):
        m_file = self.menuBar().addMenu("ファイル")
        a_open = QAction("動画ファイルを開く…", self); a_open.triggered.connect(self._open_file)
        a_cam = QAction("カメラを選択…", self); a_cam.triggered.connect(self._open_camera)
        m_file.addAction(a_open); m_file.addAction(a_cam)

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "動画選択", "", "Videos (*.mp4 *.mov *.avi)")
        if path: self._start_source(VideoFileSource(path))

    def _open_camera(self):
        devs = CameraSource.list_devices()
        if not devs: self.video_label.setText("カメラが見つかりません"); return
        idx, ok = QInputDialog.getItem(self, "カメラ選択", "デバイス:",
                                       [f"Camera {i}" for i in devs], 0, False)
        if ok: self._start_source(CameraSource(devs[int(idx.split()[-1])]))

    def _start_source(self, source):
        self._stop()
        self.thread = InferenceThread(source)
        self.thread.frame_ready.connect(self._on_frame)
        self.thread.start()

    def _on_frame(self, frame, meta):
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, w, h, 3*w, QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(img).scaled(
            self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.fps_label.setText(f"FPS: {meta.get('fps', 0):.1f}  Frame: {meta['frame_idx']}")

    def _play_pause(self):
        if not self.thread: return
        if self.thread._paused: self.thread.resume(); self.btn_play.setText("⏸")
        else: self.thread.pause(); self.btn_play.setText("▶")

    def _stop(self):
        if self.thread: self.thread.stop(); self.thread.wait(); self.thread = None
        self.btn_play.setText("▶")
```

### Step 1-7: エントリーポイント（`main.py`）
```python
import sys
from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())

if __name__ == "__main__": main()
```

### 動作確認
- メニューから動画ファイル選択 → 再生される
- メニューからカメラ選択 → 内蔵カメラ映像が出る
- ⏹ で停止、▶ で一時停止/再開

### コミット
```
feat(phase1): video file & camera input UI with PySide6
```

### Phase 1 完了条件
- [ ] 動画ファイルを再生できる
- [ ] 内蔵 / 外部カメラを選択して再生できる
- [ ] 一時停止 / 停止が動く
- [ ] FPS とフレーム番号が表示される

---

## B.3 Phase 2: 物体検出 + トラッキング（所要 2〜3 日）

### Step 2-1: 設定ローダ（`src/utils/config.py`）
```python
import yaml
def load_config(path: str = "config/default.yaml") -> dict:
    with open(path, "r") as f: return yaml.safe_load(f)
```

### Step 2-2: YOLO 検出器（`src/detection/yolo_detector.py`）
```python
from ultralytics import YOLO
import numpy as np
from src.types import Detection

COCO_NAME = {0:"person",1:"bicycle",2:"car",3:"motorcycle",5:"bus",7:"truck"}

class YoloDetector:
    def __init__(self, weights="yolov8n.pt", device="mps", conf=0.35, iou=0.5,
                 imgsz=640, classes=None):
        self.model = YOLO(weights)
        self.device, self.conf, self.iou, self.imgsz = device, conf, iou, imgsz
        self.classes = classes or list(COCO_NAME.keys())

    def detect(self, frame: np.ndarray) -> list[Detection]:
        res = self.model.predict(frame, device=self.device, conf=self.conf,
                                 iou=self.iou, imgsz=self.imgsz,
                                 classes=self.classes, verbose=False)[0]
        out = []
        for b in res.boxes:
            x1,y1,x2,y2 = b.xyxy[0].tolist()
            cls = int(b.cls[0]); cf = float(b.conf[0])
            out.append(Detection((x1,y1,x2,y2), COCO_NAME.get(cls, str(cls)), cf))
        return out
```

### Step 2-3: トラッキング（`src/tracking/byte_tracker.py`）
```python
from ultralytics import YOLO
from collections import deque
import numpy as np
from src.types import TrackedObject

class YoloTracker:
    def __init__(self, weights="yolov8n.pt", device="mps", conf=0.35, iou=0.5,
                 imgsz=640, classes=None):
        self.model = YOLO(weights)
        self.device, self.conf, self.iou, self.imgsz = device, conf, iou, imgsz
        self.classes = classes
        self._history: dict[int, deque] = {}
        self._age: dict[int, int] = {}

    def track(self, frame: np.ndarray) -> list[TrackedObject]:
        res = self.model.track(frame, persist=True, tracker="bytetrack.yaml",
                               device=self.device, conf=self.conf, iou=self.iou,
                               imgsz=self.imgsz, classes=self.classes, verbose=False)[0]
        out = []
        if res.boxes.id is None: return out
        for b in res.boxes:
            tid = int(b.id[0])
            x1,y1,x2,y2 = b.xyxy[0].tolist()
            cx, cy = (x1+x2)/2, (y1+y2)/2
            h = self._history.setdefault(tid, deque(maxlen=30))
            h.append((cx, cy))
            self._age[tid] = self._age.get(tid, 0) + 1
            out.append(TrackedObject(
                track_id=tid, bbox=(x1,y1,x2,y2),
                cls=res.names[int(b.cls[0])], conf=float(b.conf[0]),
                velocity=self._velocity(h), history=h, age=self._age[tid],
                distance_m=None))
        return out

    def _velocity(self, hist) -> tuple[float,float]:
        if len(hist) < 2: return (0.0, 0.0)
        pts = np.array(list(hist)[-5:]); t = np.arange(len(pts))
        return float(np.polyfit(t, pts[:,0], 1)[0]), float(np.polyfit(t, pts[:,1], 1)[0])
```

### Step 2-4: 描画（`src/render/renderer.py` 最小版）
```python
import cv2, numpy as np
from src.types import TrackedObject

CLASS_COLOR = {"person":(0,255,0),"car":(255,128,0),"truck":(255,128,0),
               "bus":(255,128,0),"motorcycle":(0,200,255),"bicycle":(0,200,255)}

def draw_tracks(frame: np.ndarray, tracks: list[TrackedObject]) -> np.ndarray:
    img = frame.copy()
    for t in tracks:
        x1,y1,x2,y2 = map(int, t.bbox)
        c = CLASS_COLOR.get(t.cls, (200,200,200))
        cv2.rectangle(img, (x1,y1), (x2,y2), c, 2)
        cv2.putText(img, f"{t.cls}#{t.track_id}", (x1, y1-6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1, cv2.LINE_AA)
        cx, cy = (x1+x2)//2, (y1+y2)//2; vx, vy = t.velocity
        cv2.arrowedLine(img, (cx,cy), (int(cx+vx*5), int(cy+vy*5)),
                        (0,255,255), 2, tipLength=0.3)
    return img
```

### Step 2-5: パイプライン統合（`src/pipeline.py`）
```python
import numpy as np
from src.tracking.byte_tracker import YoloTracker

class Pipeline:
    def __init__(self, cfg: dict):
        d = cfg["detector"]
        self.tracker = YoloTracker(weights=d["weights"], device=d["device"],
                                   conf=d["conf"], iou=d["iou"],
                                   imgsz=d["imgsz"], classes=d["classes"])

    def process(self, frame: np.ndarray):
        return {"tracks": self.tracker.track(frame)}
```

### Step 2-6/7: スレッドと UI 更新
- `InferenceThread` で `pipeline.process(frame)` を呼ぶ
- `MainWindow._on_frame` で `meta["tracks"]` を `draw_tracks` に渡してから QImage 化

### コミット
```
feat(phase2): YOLO detection + ByteTrack tracking with overlay
```

### Phase 2 完了条件
- [ ] 人・車に BB と ID が付く
- [ ] ID が次フレームでも維持される
- [ ] 速度ベクトル矢印が出る
- [ ] Mac で 720p 20fps 以上

---

## B.4 Phase 3: 路面・車線（所要 3〜4 日・概略）

1. `src/segmentation/road_segmenter.py` — SegFormer-b0、3 フレームに 1 回推論、`road=1/sidewalk=2/other=0`
2. `src/lane/classical.py` — ROI → Canny → Hough → 左右分類 → 平均線 → `LaneInfo`
3. `src/utils/geometry.py` — 消失点・危険ゾーン台形
4. `src/lane/lane_detector.py` — LDW 判定（30/50px ヒステリシス）
5. パイプライン統合 — `SceneContext` 構築、Renderer に車線・危険ゾーン描画

### Phase 3 完了条件
- [ ] road_mask が毎フレーム取得できる
- [ ] 自車レーン台形が動的に出る
- [ ] 歩道歩行者が警告対象から外れる
- [ ] LDW が安定動作（チャタリングしない）

---

## B.5 Phase 4: 衝突予測ロジック（所要 4〜5 日・概略）

1. `src/depth/ipm_fallback.py` — IPM ベース距離推定
2. `src/depth/monocular.py` — Depth Anything V2、IPM でスケール固定
3. `src/prediction/ttc.py` — 距離履歴から TTC
4. `src/prediction/trajectory.py` — 30 フレーム履歴に直線フィット、自車レーンとの交点
5. `src/prediction/intrusion.py` — 飛び出し / 対向車侵入（§2.9.5）
6. `src/prediction/risk_analyzer.py` — 統合
7. `src/alert/alert_manager.py` — 優先度・cooldown
8. Renderer に警告表示（赤枠点滅 + 右上サマリーパネル）

### 動作確認シーンと期待警告
| シーン | 期待される警告 |
|--------|---------------|
| 飛び出し | "⚠ 飛び出し" critical |
| 前車停止→発進 | "前車発進" info |
| 車間が詰まる | "⚠ 車間注意" warn |
| 対向車右折 | "⚠ 衝突注意" critical |
| 直進対向車 | 警告なし |

### Phase 4 完了条件
- [ ] 各シーンで期待警告が出る
- [ ] 直進対向車では警告が出ない（重要）
- [ ] チャタリング 1 警告/秒以下

---

## B.6 Phase 5: 視認性改善（所要 2 日・概略）

1. `src/enhancement/night_mode.py` — LAB+CLAHE+ガンマ+デノイズ
2. `src/enhancement/hdr.py` — 単一フレームから疑似多重露光 → Mertens
3. `src/enhancement/enhancer.py` — 自動切替判定
4. UI トグル追加
5. ON/OFF 切替で検出数を比較

### Phase 5 完了条件
- [ ] 夜間動画で OFF→ON で検出 mAP +10% 以上
- [ ] 自動切替が安定

---

## B.7 Phase 6: 信号・標識 日本仕様（所要 2〜4 週・概略）

1. データ収集: 自前 + 公開データから日本フレーム抽出（信号 1500 / 標識 1500 枚）
2. アノテーション: Roboflow / CVAT、§2.8 のクラス
3. 学習: `scripts/train_jp_signs.py`、`yolov8s.pt` ベース、100 epoch
4. 推論統合: `src/signs/jp_sign_detector.py`, `src/signs/signal_color.py`
5. 警告ロジック: 赤信号通過警告

### Phase 6 完了条件
- [ ] 自前動画で信号色を 95% 以上正答
- [ ] 標識を mAP@0.5 ≥ 0.7

---

## B.8 Phase 7: 仕上げ（所要 1〜2 週）

- 死角検知 / DMS（別カメラ前提、後回し可）
- 雨・霧・逆光対応
- ONNX / CoreML 化
- 評価指標自動計測スクリプト
- README / 操作マニュアル

---

## B.9 全体の所要見積（1人想定）
| Phase | 期間 |
|-------|------|
| 0 | 0.5 日 |
| 1 | 1〜2 日 |
| 2 | 2〜3 日 |
| 3 | 3〜4 日 |
| 4 | 4〜5 日 |
| 5 | 2 日 |
| 6 | 2〜4 週（データ依存） |
| 7 | 1〜2 週 |
| **合計** | **約 6〜8 週（標識学習込み）** |

---

## B.10 ブランチ運用
- `main`: 安定版
- `phase/N-XXX`: 各 Phase の作業ブランチ
- Phase 完了ごとに `main` へ PR

## B.11 詰まったときの参照
- Ultralytics YOLO: https://docs.ultralytics.com/
- HuggingFace Transformers: https://huggingface.co/docs/transformers
- PySide6: https://doc.qt.io/qtforpython-6/
- OpenCV: https://docs.opencv.org/

---

# C. Raspberry Pi 5 + Coral Edge TPU 移植手順

> この章は **特定エージェント非依存** で書く。Claude Code / Codex / 人間のいずれが読んでも
> そのまま実行できるよう、コマンド・前提条件・受け入れ基準を明示する。
> 「自分が〜する」のような実行主体前提の表現は使わない。

## C.0 目的と全体像

YOLO11n を **INT8 量子化 TFLite → Edge TPU 用コンパイル**し、Raspberry Pi 5 + Google Coral
USB Accelerator で推論する。同一コードベースのまま、推論に使う重みファイルを差し替えるだけで
3 環境 (Mac=PyTorch/MPS、Pi=CPU、Pi+Coral=TPU) を切り替えられる。

| 環境 | 重みファイル | device 設定 |
|---|---|---|
| Mac (開発・基準) | `models/yolo11n.pt` | `auto` (MPS) |
| Mac / Pi の CPU 検証 | `models/yolo11n_full_integer_quant.tflite` | `cpu` |
| Pi 5 + Coral USB | `models/yolo11n_full_integer_quant_edgetpu.tflite` | `cpu` (delegate 自動) |

**重要な制約**:
- Coral Edge TPU は **INT8 量子化済み TFLite を Edge TPU 用にコンパイルした `.tflite` 限定**でしか動かない。
- `edgetpu_compiler` は **x86_64 Linux 専用**。ARM の Pi 上でも Apple Silicon Mac ネイティブでも動かない。
  → モデル変換は「Mac/x86 章」で行い、生成物を Pi へ転送する。
- 推論呼び出し (`YOLO(weights).predict()`) は全形式で共通。後段 (ByteTrack/危険判定) は無改修。

---

## C.1 Mac / x86 章 — モデル変換と転送

実行環境: Apple Silicon Mac (Docker Desktop 導入済み) もしくは x86_64 Linux マシン。

### C.1-1 INT8 TFLite の生成 (Mac でネイティブ実行可)

前提: `ultralytics` と `tensorflow` が導入された Python 環境 (本リポジトリの conda env `main` で確認済み)。

```bash
cd <リポジトリルート>
PYTHONPATH=. python -m ultralytics export model=models/yolo11n.pt format=tflite int8=True imgsz=320
# もしくは: yolo export model=models/yolo11n.pt format=tflite int8=True imgsz=320
```

出力: `models/yolo11n_saved_model/yolo11n_full_integer_quant.tflite`

`models/` 直下へコピーする (プロファイルが参照するパスに合わせる):

```bash
cp models/yolo11n_saved_model/yolo11n_full_integer_quant.tflite models/yolo11n_full_integer_quant.tflite
```

補足: INT8 量子化の精度はキャリブレーション画像に依存する。`data=<画像ディレクトリ or データセット yaml>`
を渡すと実映像に合わせた量子化ができ精度が上がる。省略時は Ultralytics の既定キャリブが使われる。

### C.1-2 Edge TPU 用コンパイル (Docker amd64 で実行) ★検証済みレシピ

`edgetpu_compiler` は x86_64 Linux 専用のため、Apple Silicon Mac では Docker の amd64
エミュレーションを使う。前提: Docker Desktop が起動しており、amd64 イメージを実行できること
(確認コマンド: `docker run --rm --platform linux/amd64 alpine uname -m` が `x86_64` を返す)。

**重要 (ハマりどころ)**: 手動で TF/onnx2tf のバージョンを選ぶと `QuantizeModel` 引数不一致や
`CONV_2D version` 非対応で失敗する (2026-05-21 に 7 通り試して全滅)。
**Ultralytics 公式イメージ `ultralytics/ultralytics:latest-cpu` を使い、numpy だけ `<2` に下げる**
のが唯一通った方法。公式イメージは tf/onnx2tf を整合済みで持つため、これに任せるのが確実
(2026-05-21 検証時: tensorflow 2.19.0 / onnx2tf 1.28.8 / numpy 1.26.4 で成功)。

```bash
docker pull --platform linux/amd64 ultralytics/ultralytics:latest-cpu

docker run --rm --platform linux/amd64 \
  -v <リポジトリルート>:/work \
  --entrypoint bash ultralytics/ultralytics:latest-cpu -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq curl gnupg ca-certificates
    echo "deb [signed-by=/usr/share/keyrings/coral.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main" \
      > /etc/apt/sources.list.d/coral-edgetpu.list
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/coral.gpg
    apt-get update -qq && apt-get install -y -qq edgetpu-compiler
    pip install --quiet "numpy<2"        # 公式イメージの numpy 2.x が TF と衝突するため必須
    cd /work
    yolo export model=models/yolo11n.pt format=edgetpu imgsz=320
  '
```

出力: `models/yolo11n_saved_model/yolo11n_full_integer_quant_edgetpu.tflite` (+ `*_edgetpu.log`)。
`models/` 直下へコピーして使う:

```bash
cp models/yolo11n_saved_model/yolo11n_full_integer_quant_edgetpu.tflite models/yolo11n_full_integer_quant_edgetpu.tflite
```

検証結果 (2026-05-21, imgsz=320): `Compilation succeeded!`。コンパイルログの op マッピングで
**CONV_2D 208/209、DEPTHWISE_CONV_2D 6/6 が Edge TPU にマップ**。一部 op は
`More than one subgraph is not supported` で CPU 実行になるが (YOLO 系では標準的)、
重い畳み込みの大半が TPU に乗るため実用的な高速化が見込める。

注意点:
- 入力は **fully integer quantized (int8 入出力)** が必要。`format=edgetpu` は自動でこれを生成する。
- imgsz を変える場合は再度この手順で対応する `_edgetpu.tflite` を作る (入力サイズはモデルに焼き込まれる)。
- `data=<代表画像>` を渡すと実映像でキャリブされ精度が上がる (省略時は既定キャリブ)。

### C.1-3 Pi への転送

```bash
scp models/yolo11n_full_integer_quant_edgetpu.tflite <user>@<pi-host>:<repo>/models/
scp models/yolo11n_full_integer_quant.tflite        <user>@<pi-host>:<repo>/models/
```

(`models/*` は `.gitignore` 対象。git ではなく scp/rsync 等で転送する。)

### C.1-4 Mac 章の受け入れ基準
- [ ] `models/yolo11n_full_integer_quant.tflite` が生成されている
- [ ] `models/yolo11n_full_integer_quant_edgetpu.tflite` が生成されている
- [ ] `scripts/compare_int8.py` で pt 版と INT8 版の検出率を比較し、person/bicycle の劣化が許容範囲か確認済み
      (本プロジェクトは「検出感度 > 速度」が原則。劣化が大きい場合は imgsz 引き上げや再キャリブを検討)

---

## C.2 Pi 章 — Coral runtime 導入・推論・ベンチ

実行環境: Raspberry Pi 5 / Raspberry Pi OS Bookworm (64-bit) / Coral USB Accelerator 接続済み。
この章は Pi 上で実行する。Pi 上に Claude Code / Codex を導入して本章に従わせてもよい。

### C.2-1 Edge TPU runtime (libedgetpu) の導入

```bash
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" \
  | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/coral.gpg
sudo sed -i 's|deb https|deb [signed-by=/usr/share/keyrings/coral.gpg] https|' \
  /etc/apt/sources.list.d/coral-edgetpu.list
sudo apt-get update
# 標準クロック版 (発熱・消費を抑える)。最大クロックは libedgetpu1-max (要冷却)
sudo apt-get install -y libedgetpu1-std
```

Coral USB を一度抜き差しして OS に認識させる (USB3 ポート推奨)。

### C.2-2 Python 依存の導入

```bash
cd <repo>
python3 -m venv .venv && source .venv/bin/activate   # 既存環境があれば流用可
pip install ultralytics
pip install tflite-runtime    # 入らない場合は pycoral 経由 or ai-edge-litert を検討
```

### C.2-3 Coral 認識確認

```bash
lsusb | grep -i "Global Unichip\|Google"   # Coral が見えるか
```

最小推論テスト (検出が 0 件でもエラーなく完了すれば配線・runtime は OK):

```bash
cd <repo>
PYTHONPATH=. python3 -c "
from ultralytics import YOLO
m = YOLO('models/yolo11n_full_integer_quant_edgetpu.tflite')
r = m.predict('data/videos/<test_image_or_video>', imgsz=320, verbose=True)
print('OK', len(r))
"
```

### C.2-4 アプリ起動 (Coral プロファイル)

```bash
cd <repo>
PYTHONPATH=. python3 main.py --config config/coral_edgetpu.yaml
```

`config/coral_edgetpu.yaml` は `models/yolo11n_full_integer_quant_edgetpu.tflite` / `imgsz: 320` /
`device: cpu` (delegate は Ultralytics がファイル名から自動選択) を指す。

### C.2-5 ベンチマーク (imgsz 確定)

`config/coral_edgetpu.yaml` の `detector.imgsz` を 320 と 480 で切り替え (それぞれ対応する
`_edgetpu.tflite` が必要)、UI の遅延率/fps 表示で推論時間と検出率を比較する。
本プロジェクトは「検出感度 > 速度」が原則のため、fps が許容範囲なら検出率の高い設定を採る。

### C.2-6 Pi 章の受け入れ基準
- [ ] `lsusb` で Coral が認識される
- [ ] `*_edgetpu.tflite` での最小推論がエラーなく完了する
- [ ] `main.py --config config/coral_edgetpu.yaml` が起動し、映像上に検出枠が出る
- [ ] 320 / 480 の fps・検出率を計測し、採用 imgsz を決定済み
- [ ] CPU 版 (`config/tflite_cpu.yaml`) と TPU 版で fps が改善していることを確認

---

## C.3 トラブルシュート
- `edgetpu_compiler` が「Model not quantized」→ 入力が int8 量子化済みでない。`*_full_integer_quant.tflite` を使う。
- Pi で TPU が使われず遅い → libedgetpu 未導入、または Ultralytics がファイル名から delegate を選べていない
  (`*_edgetpu.tflite` のファイル名を保つこと)。`lsusb` と runtime 導入を再確認。
- Coral が熱で throttling → `libedgetpu1-std` を使う、冷却を追加、`libedgetpu1-max` は冷却前提。
- 検出率が CPU 版より大きく落ちる → コンパイルログの CPU フォールバック op が多い可能性。imgsz や
  量子化キャリブを見直す。
