# 実装計画書

## 計画の全体像

このアプリは以下の **4フェーズ** に分けて開発する。  
各フェーズは独立して動作確認できる状態で完了させる。

```
フェーズ1  →  フェーズ2  →  フェーズ3  →  フェーズ4
プロジェクト   バックエンド   フロントエンド  ラズパイ
初期化         実装           実装            デプロイ
```

---

## フェーズ1: プロジェクト初期化

### 目標
Rust プロジェクトの土台を作り、"Hello World" レベルのサーバーが起動できる状態にする。

### タスク一覧

| # | 作業内容 | 成果物 |
|---|---|---|
| 1-1 | `cargo new video-viewer` でプロジェクト作成 | `Cargo.toml`, `src/main.rs` |
| 1-2 | 依存クレートを `Cargo.toml` に追加 | 更新済み `Cargo.toml` |
| 1-3 | ディレクトリ構成を作成 | `src/handlers/`, `static/` など |
| 1-4 | `config.json` のひな形を作成 | `config.json` |
| 1-5 | 設定ファイル読み込みモジュールを実装 | `src/config.rs` |
| 1-6 | `GET /health` だけ返す最小サーバーを起動 | `src/main.rs` |

### 完了条件
```bash
cargo run
# → "Listening on http://0.0.0.0:8080" が表示される
curl http://localhost:8080/health
# → {"status":"ok"} が返る
```

### ファイル構成（フェーズ1完了時）
```
video-viewer/
├── Cargo.toml
├── config.json
└── src/
    ├── main.rs
    └── config.rs
```

---

## フェーズ2: バックエンド実装

### 目標
動画一覧の取得・ストリーミング再生・ダウンロードが curl で動作する状態にする。

### タスク一覧

| # | 作業内容 | 成果物 |
|---|---|---|
| 2-1 | 動画ファイルスキャン機能を実装 | `src/scanner.rs` |
| 2-2 | `GET /api/videos` エンドポイントを実装 | `src/handlers/videos.rs` |
| 2-3 | `GET /video/*path` Range対応ストリーミングを実装 | `src/handlers/stream.rs` |
| 2-4 | `GET /download/*path` ダウンロードを実装 | `src/handlers/download.rs` |
| 2-5 | パストラバーサル防止ロジックを実装 | `src/handlers/mod.rs` |
| 2-6 | Axum ルーターに全エンドポイントを登録 | `src/main.rs` |
| 2-7 | SIGTERM グレースフルシャットダウンを実装 | `src/main.rs` |

### 完了条件
```bash
# 動画一覧が取得できる
curl http://localhost:8080/api/videos

# 動画がストリーミングできる（Range ヘッダー対応）
curl -H "Range: bytes=0-1023" http://localhost:8080/video/test.mp4 -o /dev/null

# ダウンロードできる
curl -OJ http://localhost:8080/download/test.mp4

# パストラバーサルが拒否される（403 が返る）
curl http://localhost:8080/video/../../../etc/passwd
```

### ファイル構成（フェーズ2完了時）
```
video-viewer/
├── Cargo.toml
├── config.json
└── src/
    ├── main.rs
    ├── config.rs
    ├── scanner.rs
    └── handlers/
        ├── mod.rs
        ├── videos.rs
        ├── stream.rs
        └── download.rs
```

---

## フェーズ3: フロントエンド実装

### 目標
スマートフォンのブラウザで動画一覧・再生・ダウンロードが操作できる状態にする。

### タスク一覧

| # | 作業内容 | 成果物 |
|---|---|---|
| 3-1 | HTML 骨格・レイアウト作成（モバイルファースト） | `static/index.html` |
| 3-2 | グリッド一覧 UI を CSS で実装 | `static/style.css` |
| 3-3 | `/api/videos` を fetch して一覧を描画する JS 実装 | `static/app.js` |
| 3-4 | 動画プレーヤー画面を実装（タップで展開） | `static/app.js` |
| 3-5 | ダウンロードボタンを実装 | `static/app.js` |
| 3-6 | 検索バー・ソート機能を実装 | `static/app.js` |
| 3-7 | ダークモード対応（`prefers-color-scheme`） | `static/style.css` |
| 3-8 | 静的ファイルをバイナリに内包（`include_str!`） | `src/main.rs` |

### 完了条件
- スマートフォンブラウザで `http://<IP>:8080` を開くと動画一覧が表示される
- 動画をタップするとインライン再生できる
- ダウンロードボタンでファイルが保存できる
- 検索バーでファイル名を絞り込める
- 画面を回転しても崩れない

### ファイル構成（フェーズ3完了時）
```
video-viewer/
├── Cargo.toml
├── config.json
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── src/
    ├── main.rs       ← static/ をバイナリ内包
    ├── config.rs
    ├── scanner.rs
    └── handlers/
        ├── mod.rs
        ├── videos.rs
        ├── stream.rs
        └── download.rs
```

---

## フェーズ4: Raspberry Pi 5 デプロイ

### 目標
Raspberry Pi 5 上でサーバーが自動起動し、親システムから制御できる状態にする。

### タスク一覧

| # | 作業内容 | 成果物 |
|---|---|---|
| 4-1 | ARM64 向けクロスコンパイルの設定 | `.cargo/config.toml` |
| 4-2 | リリースビルドを ARM64 で生成 | `video-viewer`（バイナリ） |
| 4-3 | バイナリと設定ファイルをラズパイに転送 | ラズパイ上のファイル |
| 4-4 | ラズパイ上で動作確認 | — |
| 4-5 | systemd サービスファイルを作成・登録 | `video-viewer.service` |
| 4-6 | 親システム（Python）からの起動・停止を確認 | — |
| 4-7 | ヘルスチェックが正常に動作することを確認 | — |

### 完了条件
```bash
# ラズパイ再起動後も自動起動する
sudo reboot
systemctl status video-viewer  # → active (running)

# Python 親システムから制御できる
python3 test_control.py  # → 起動・ヘルスチェック・停止が成功
```

---

## オプションフェーズ（余裕があれば）

| フェーズ | 内容 |
|---|---|
| 5-A | サムネイル生成（ffmpeg 連携） |
| 5-B | フォルダ変更の自動検知（notify クレート） |
| 5-C | Basic 認証の追加 |

---

## 実装の優先順位まとめ

```
必須（Must）
  └─ フェーズ1〜4

あると良い（Should）
  └─ 5-A サムネイル
  └─ 5-B 自動検知

余裕があれば（Could）
  └─ 5-C 認証
```

---

## 各フェーズで守るルール

1. **1フェーズ完了ごとに動作確認する** — 後でまとめてデバッグしない
2. **フロントエンドはフェーズ2が完全に動いてから始める** — API が安定してからUI を作る
3. **ラズパイへのデプロイはフェーズ3完了後** — ローカルで十分テストしてから転送する
4. **設定値はすべて `config.json` に集める** — コード内にパスやポート番号をハードコードしない
