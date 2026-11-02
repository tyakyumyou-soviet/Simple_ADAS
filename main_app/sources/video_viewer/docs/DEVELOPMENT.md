# 開発・ビルド・デプロイ手順

## 開発環境セットアップ

### 必要ツール

```bash
# Rust インストール
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# ARM64 クロスコンパイルターゲット追加
rustup target add aarch64-unknown-linux-gnu

# クロスコンパイル用リンカー（macOS の場合）
brew install SergioBenitez/osxct/aarch64-unknown-linux-gnu

# クロスコンパイル用リンカー（Ubuntu/Debian の場合）
sudo apt install gcc-aarch64-linux-gnu
```

### `.cargo/config.toml`（クロスコンパイル設定）

```toml
[target.aarch64-unknown-linux-gnu]
linker = "aarch64-unknown-linux-gnu-gcc"
```

---

## ビルド

### ローカル開発用（x86_64）

```bash
cargo build
cargo run -- --config config.json
```

### Raspberry Pi 5 向け（ARM64）

```bash
cargo build --release --target aarch64-unknown-linux-gnu
```

出力: `target/aarch64-unknown-linux-gnu/release/video-viewer`

### バイナリサイズ最適化（任意）

`Cargo.toml` に追記:
```toml
[profile.release]
opt-level = 3
lto = true
codegen-units = 1
strip = true
```

---

## Raspberry Pi 5 へのデプロイ

```bash
# バイナリを転送
scp target/aarch64-unknown-linux-gnu/release/video-viewer pi@raspberrypi.local:~/

# 設定ファイルを転送
scp config.json pi@raspberrypi.local:~/

# Raspberry Pi 上で動作確認
ssh pi@raspberrypi.local
./video-viewer --config config.json
```

---

## systemd サービス設定（自動起動）

`/etc/systemd/system/video-viewer.service`:

```ini
[Unit]
Description=Video Viewer Web Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/home/pi/video-viewer --config /home/pi/config.json
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable video-viewer
sudo systemctl start video-viewer
sudo systemctl status video-viewer
```

---

## 親システムからの制御

### Python から制御する場合

```python
import subprocess
import signal
import time
import urllib.request

class VideoViewerProcess:
    def __init__(self, binary_path: str, config_path: str):
        self.binary_path = binary_path
        self.config_path = config_path
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            [self.binary_path, "--config", self.config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # 起動完了を待つ（stdout に "Listening on" が出るまで）
        for line in self.proc.stdout:
            if b"Listening on" in line:
                break

    def stop(self):
        if self.proc:
            self.proc.send_signal(signal.SIGTERM)
            self.proc.wait(timeout=30)

    def health_check(self) -> bool:
        try:
            urllib.request.urlopen("http://localhost:8080/health", timeout=2)
            return True
        except Exception:
            return False
```

### Rust から制御する場合

```rust
use std::process::{Child, Command};
use std::time::Duration;

struct VideoViewerProcess {
    child: Child,
}

impl VideoViewerProcess {
    fn start(binary: &str, config: &str) -> std::io::Result<Self> {
        let child = Command::new(binary)
            .args(["--config", config])
            .spawn()?;
        Ok(Self { child })
    }

    fn stop(&mut self) {
        // SIGTERM でグレースフルシャットダウン
        unsafe { libc::kill(self.child.id() as i32, libc::SIGTERM); }
        let _ = self.child.wait();
    }
}
```

---

## 設定ファイル (`config.json`)

```json
{
  "video_dir": "/home/pi/videos",
  "port": 8080,
  "host": "0.0.0.0",
  "thumbnail_dir": "/home/pi/.cache/video-viewer/thumbs",
  "auth": null
}
```

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `video_dir` | string | `"./videos"` | 動画フォルダの絶対パス |
| `port` | number | `8080` | リッスンポート |
| `host` | string | `"0.0.0.0"` | バインドアドレス |
| `thumbnail_dir` | string \| null | `null` | null でサムネイル無効 |
| `auth` | object \| null | `null` | null で認証無効 |

認証あり設定例:
```json
{
  "auth": {
    "username": "pi",
    "password": "your_password"
  }
}
```

---

## ログ

```bash
# journald でリアルタイム確認
sudo journalctl -u video-viewer -f

# 直接実行時のログレベル設定
RUST_LOG=info ./video-viewer --config config.json
RUST_LOG=debug ./video-viewer --config config.json
```

---

## テスト

```bash
# 単体テスト
cargo test

# Range リクエストの動作確認
curl -v -H "Range: bytes=0-1023" http://localhost:8080/video/test.mp4

# ヘルスチェック
curl http://localhost:8080/health

# パストラバーサル攻撃テスト（403 が返ることを確認）
curl http://localhost:8080/video/../../../etc/passwd
```
