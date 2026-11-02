# CLAUDE_ADVICE.md — Claude からのアドバイス

> 本書は Claude が `PLAN.md` / `PROGRESS.md` / 設定 YAML / 実装ファイルを確認した上での現状分析・改善提案。
> 実装は Codex が進行中。本書は意思決定の参考資料。
> 最終更新: 2026-05-11 11:25（PROGRESS.md エントリ 11:21 まで反映）

---

## 1. 現状サマリ

### 1.1 進捗
- Phase 0〜5 実装完了、Phase 6 はモデル統合のみ、Phase 7 一部完
- **Codex の修正エントリ 19 件、うち過去 100 分で速度関連が 10 件**
- アプリは動作（合成デモで警告発火確認済み）、ruff clean / pytest 8 passed

### 1.2 現在のプロファイル状況
| プロファイル | imgsz | 処理幅 | 解析fps | seg | depth | signs | enhance |
|------------|-------|--------|---------|-----|-------|-------|---------|
| **default** | 640 | 1280 | 連続 | 3f毎 | 2f毎 | 毎f | ON |
| **realtime_cpu** | 320 | 540 | 10 | **OFF** | **OFF** | **OFF** | **OFF** |
| **turbo_cpu** | 256 | 360 | 6 | OFF | OFF | 30f毎 | OFF |
| **view_only** | — | 720 | 0 | OFF | OFF | OFF | OFF |
| **full_quality** | 640 | 1280 | 連続 | 3f毎 | 2f毎 | 2f毎 | ON |

### 1.3 11:21 の修正で機能が削られた
最新 11:21 のエントリで「**信号/標識検出と視認性補正は標準UIとパイプライン処理から外した**」とある。
- これは速度のために要件 1.4（HDR/夜間）と 1.6（信号・標識）を一時的に切ったということ
- ユーザー要件には残っているので **いずれ復活させる必要がある**。今は退避策

---

## 2. 真の問題（最重要）

### 🔴 ボトルネックは MPS が使えていないこと

PROGRESS.md 未解決#8: `arm64 / PyTorch MPS built=True だが torch.backends.mps.is_available() が False になる原因確認` が **Phase 0 から放置されたまま**。

**11:12 の Codex 計測**: 標準設定で **初回解析に 1.46 秒**。これは CPU 推論の典型値で、MPS が効けば **150-300ms** まで落ちる。

### Codex の取り組みの構造的限界
| 現在の対応 | 限界 |
|----------|------|
| imgsz 320→256 まで縮小 | これ以上下げると小さな歩行者を見落とす（要件 1.1 違反） |
| 処理幅 540→360px へ縮小 | 遠方の車・標識を識別不能 |
| analysis_fps 10→6 へ | 30km/h で 1.4m おきの離散判定。飛び出し検知が間に合わない |
| 機能を OFF | 要件 1.4 / 1.6 と直接矛盾 |
| **最終的にどこかで詰む。これらは「症状の緩和」であり「治療」ではない** | |

---

## 3. 提案（優先度順）

### 🔥 S-1. MPS 診断（最優先・0.5 日）

未解決#8 を解決すれば、上記すべての制約が緩む。

```python
# scripts/diagnose_mps.py
import platform, sys, subprocess, torch
print("machine:", platform.machine())
print("python exec:", sys.executable)
print("python arch:", subprocess.check_output(["file", sys.executable]).decode())
print("arch:", subprocess.check_output(["arch"]).decode().strip())
print("torch:", torch.__version__)
print("MPS built:", torch.backends.mps.is_built())
print("MPS available:", torch.backends.mps.is_available())
print("macOS:", platform.mac_ver()[0])
try:
    x = torch.tensor([1.0], device="mps"); print("MPS tensor OK:", x)
except Exception as e: print("MPS tensor FAIL:", e)
```

**よくある原因**:
1. **Python が x86_64（Rosetta）で動いている** ← 最有力候補
   - 解決: `brew install python@3.11` で arm64 ネイティブ Python、`.venv` 作り直し
2. macOS 12.3 未満
3. PyTorch 古い → `pip install --upgrade torch torchvision`
4. venv が古い Python 由来

**期待効果**: YOLOv8n 推論 1460ms → **150-300ms（5-10倍）**

---

### 🔥 S-2. CoreML 化（MPS ダメなら / 0.5 日）

Apple Neural Engine を使う。Ultralytics が 1 行で対応。

```python
from ultralytics import YOLO
YOLO("models/yolov8n.pt").export(format="coreml", nms=True, half=True)
# → yolov8n.mlpackage が出る
```

差し替えるだけで Ultralytics が自動で CoreML ランタイム経由になる。**M1 で YOLOv8n が 10-30ms**。
MPS と CoreML どちらかが効けば 11:21 で削った機能を全て復活させた上で標準動作する。

---

### ⭐ A-1. 完全非同期パイプライン化（1 日）

11:12 で「初回解析 1.46s で画面が出ない」を `raw_preview_before_analysis` で応急処置済み。
11:21 で「スキップ中に検出枠が消える」を前回結果の継続描画で対処済み。
→ **これらは構造的に解決すべき**。

**提案構造**:
```
Producer (capture)  ─ 入力FPSで読込
        │ frame_queue (maxsize=1, latest-only put)
        ▼
Inference Worker    ─ 自分のペースで推論、結果を最新だけ保持
        │ result_holder (Lock 付き dict)
        ▼
UI Thread (33ms毎)  ─ 最新フレーム+最新結果を合成して描画
```

これで `analysis_fps`, `adaptive_skip`, `raw_preview_before_analysis`, `display_every_n_frames` の **4 つの絡まった設定が全部不要になる**。再生は常に滑らか、推論は別レーンで自由なペース。

---

### ⭐ A-2. プロファイリングを文化に（即日）

Codex の振動の原因は「推測修正」。次のいずれかを 1 度走らせれば、本当の犯人がわかる：

```bash
pip install py-spy
py-spy record -o profile.svg --rate 100 -- python main.py
# or
python -c "import cProfile, main; cProfile.run('main.main()', sort='cumulative')"
```

PROGRESS.md ルールに 1 行追加することを推奨：

> **速度改善 PR は、修正前後のベンチマーク（YOLO推論ms / パイプライン全体ms / 表示FPS）を必ず記録すること**

これだけで 振動 → 収束 に変わる。

---

### 💡 B 級（合算で効く小ネタ）

| 案 | 効果 | 工数 |
|----|------|------|
| YOLO ウォームアップ（起動時にダミー3回 predict）| 初回 1.46s を後ろ倒し | 0.5h |
| BGR→RGB をやめて `QImage.Format_BGR888` 直接渡し | 描画 5ms 短縮 | 0.5h |
| `QPixmap.scaled` を `FastTransformation` に | 描画数 ms 短縮 | 0.5h |
| Depth Anything を default OFF（IPM のみ）| 200ms/frame 削減 | 0.5h |
| ByteTrack のオプティカルフロー補間 | 推論 1/2 回 | 1日 |

---

### 💡 C 級（ブレイクスルー候補・実験）

#### C-1. Apple Vision Framework
macOS ネイティブ。Neural Engine を直接叩く。PyObjC 経由で呼び出し可能。
**人/車検出だけなら 5ms 程度**。YOLO 完全置換も視野。

#### C-2. MediaPipe Object Detection
Google 製、CPU で実用 30fps。`pip install mediapipe` で即試せる。
精度は YOLOv8n より少し落ちるが、Mac の体感は段違い。

これらは「速度優先」モードの選択肢として実装する価値あり。

---

## 4. 機能削除エントリへの懸念（11:21）

11:21 で信号・標識・HDR を標準パイプラインから外したのは**緊急避難として妥当**だが、放置すると：

- 要件 1.4（HDR・夜間モード）が消える
- 要件 1.6（信号・標識認識）が消える
- 「簡易ADAS」が「簡易物体検出」に格下げ

**対応案**: PROGRESS.md / PLAN.md に「外した機能は MPS/CoreML 対応後に復活させる」と明記し、復活タスクを Phase 7 に追加。

---

## 5. ロードマップ（推奨）

### Day 1（今日）
- [ ] `scripts/diagnose_mps.py` 作成・実行 → 原因特定
- [ ] `py-spy` でプロファイル取得
- [ ] PROGRESS.md にベンチマーク記録ルール追加

### Day 2（MPS が直った場合）
- [ ] realtime_cpu の imgsz を 416 まで戻す
- [ ] Depth Anything OFF（IPM のみ）に変更し恒久化
- [ ] 信号・標識・HDR を復活
- [ ] full_quality を MPS デフォルトに

### Day 2（MPS が直らない場合）
- [ ] CoreML エクスポート → `models/yolov8n.mlpackage`
- [ ] SegFormer も CoreML 変換検討
- [ ] 同様に機能復活

### Day 3
- [ ] 完全非同期パイプライン化
- [ ] 不要になった `analysis_fps`, `raw_preview_before_analysis` 等を削除
- [ ] ベンチマーク値を PROGRESS.md に記録、確定

---

## 6. ユーザーへの確認

1. **目標 FPS**: 720p で 15 / 20 / 30 のどれを目指すか？
2. **MPS 診断を Codex に依頼するか？**（推奨：依頼する）
3. **CoreML 化を許可するか？**（Ultralytics 公式手順、ライセンス上問題なし）
4. **削った機能（信号・HDR）はいずれ復活させる前提でよいか？**
5. **Depth Anything は本当に必要か？**（IPM で Phase 4 まで完成可能）

---

## 7. Codex への伝達文（コピペ用）

> Claude からの指示：速度改善の試行錯誤を一旦止め、まず根本原因を特定してほしい。
> 1. `scripts/diagnose_mps.py` を新規作成し（テンプレは `CLAUDE_ADVICE.md` §S-1 参照）、実行結果を PROGRESS.md に記録
> 2. `py-spy record` でプロファイルを取り、最も重い 3 関数とその時間を PROGRESS.md に記録
> 3. MPS が動かない原因が判明したら、修正方針を PROGRESS.md に書いてからコード変更に着手
> 4. 以後、速度改善 PR は修正前後のベンチマーク（YOLO推論ms / パイプライン全体ms / 表示FPS）を PROGRESS.md に必須記載

---

## 8. Claude としての結論

- **Codex は誠実に仕事しているが、根本原因（MPS）を回避し続けている**。
- **`imgsz` と `analysis_fps` の引き下げはもう限界**。これ以上下げると ADAS として機能しない。
- **次の一手は 1 つだけ**: MPS 診断 → 治療。それで全てが解ける可能性が高い。
- 仮に MPS が無理でも CoreML で同じゴールに到達できる。
- 機能を削るのではなく「速くする」方向に舵を戻すべきタイミング。

---

*Claude は実装ファイルの中身までは詳細確認していない。誤った前提があれば指摘してほしい。*
