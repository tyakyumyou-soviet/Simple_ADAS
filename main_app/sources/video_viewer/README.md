# video-viewer

Raspberry Pi 5 上で動作する、ローカル動画フォルダ向け高速軽量ウェブビューア。

- **バックエンド**: Rust + Axum（高速・低メモリ・シングルバイナリ）
- **フロントエンド**: Vanilla HTML/CSS/JS（フレームワークなし）
- **対象デバイス**: Raspberry Pi 5 (ARM64)
- **想定ユーザー**: スマートフォンブラウザ（モバイルファースト）

## ドキュメント構成

| ファイル | 内容 |
|---|---|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 要件定義書 |
| [docs/DESIGN.md](docs/DESIGN.md) | 設計書（アーキテクチャ・DB・API） |
| [docs/API.md](docs/API.md) | APIリファレンス |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 開発・ビルド・デプロイ手順 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 技術選定の意思決定記録（ADR） |

## クイックスタート

```bash
# ビルド（Raspberry Pi 5 向け ARM64）
cargo build --release --target aarch64-unknown-linux-gnu

# 実行
./target/release/video-viewer --config config.json

# デフォルト設定で起動（カレントディレクトリの videos/ フォルダを参照）
./target/release/video-viewer
```

## ディレクトリ構成

```
video-viewer/
├── src/
│   ├── main.rs          # エントリポイント・サーバー起動
│   ├── config.rs        # 設定ファイル読み込み
│   ├── scanner.rs       # 動画ファイルスキャン・キャッシュ
│   └── handlers/
│       ├── mod.rs
│       ├── videos.rs    # GET /api/videos
│       ├── stream.rs    # GET /video/:path (Range対応)
│       └── download.rs  # GET /download/:path
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── config.json          # 実行時設定
├── Cargo.toml
└── docs/                # 設計・仕様ドキュメント
```

## 親システムからの制御

このサーバーはシングルプロセスとして動作し、親システム（Python / Rust）から以下の方法で制御します。

```python
# Python からの起動例
import subprocess, signal, os

proc = subprocess.Popen(["./video-viewer", "--config", "config.json"])

# 停止
proc.send_signal(signal.SIGTERM)  # グレースフルシャットダウン
```

SIGTERM 受信時にグレースフルシャットダウンします（進行中のストリーミングを完了してから終了）。
