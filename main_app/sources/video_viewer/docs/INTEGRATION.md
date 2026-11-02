# 親プロセス統合ガイド

このドキュメントは、`video-viewer` を親プロセス（Python / Rust）から制御・統合するために必要な情報をすべて記載する。

---

## 1. サービス概要

| 項目 | 詳細 |
|---|---|
| アプリ名 | video-viewer |
| 役割 | ローカル動画フォルダをブラウザで閲覧・ダウンロードできる HTTP サーバー |
| 実行形態 | シングルバイナリ（依存ランタイムなし） |
| プロトコル | HTTP/1.1（HTTPS 非対応、LAN 内専用） |
| デフォルトポート | 8080 |
| バインドアドレス | 0.0.0.0（全インターフェース） |
| 対象ハードウェア | Raspberry Pi 5（aarch64） |
| 言語 | Rust（Axum 0.7 + Tokio） |

---

## 2. 起動・停止インターフェース

### 2.1 起動コマンド

```bash
./video-viewer <config_path>
```

| 引数 | 必須 | 説明 |
|---|---|---|
| `<config_path>` | 任意 | 設定ファイルのパス。省略時は `./config.json` を使用 |

起動成功時、**標準出力**に以下のメッセージが出力される：

```
Listening on http://0.0.0.0:8080
```

親プロセスはこの文字列を検知することで「起動完了」を判断できる。

### 2.2 停止シグナル

| シグナル | 挙動 |
|---|---|
| `SIGTERM` | グレースフルシャットダウン（推奨） |
| `SIGINT` (Ctrl+C) | グレースフルシャットダウン |
| `SIGKILL` | 強制終了（非推奨） |

グレースフルシャットダウン時は進行中のHTTPレスポンスが完了してから終了する。

### 2.3 終了コード

| コード | 意味 |
|---|---|
| `0` | 正常終了 |
| `1` | 設定ファイルの読み込み失敗 |

---

## 3. 設定ファイル仕様（config.json）

```json
{
  "video_dir": "/home/pi/videos",
  "port": 8080,
  "host": "0.0.0.0",
  "folders": [
    { "name": "通常録画", "path": "通常録画" },
    { "name": "イベント録画", "path": "イベント録画" }
  ]
}
```

### フィールド定義

| フィールド | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `video_dir` | string | ✓ | — | 動画ファイルが格納されているベースディレクトリの絶対パス |
| `port` | number | — | `8080` | HTTPサーバーがリッスンするポート番号（1〜65535） |
| `host` | string | — | `"0.0.0.0"` | バインドするIPアドレス。`"127.0.0.1"` にするとローカルのみ |
| `folders` | array | ✓ | — | 公開するフォルダの定義。必ず2要素以上を指定 |
| `folders[].name` | string | ✓ | — | フロントエンドに表示するフォルダ名（日本語可） |
| `folders[].path` | string | ✓ | — | `video_dir` からの相対パス（サブディレクトリ名） |

### ディレクトリ構造の例

```
/home/pi/videos/          ← video_dir
├── 通常録画/              ← folders[0].path
│   ├── 20241201_093012.mp4
│   └── 20241130_154500.mp4
└── イベント録画/           ← folders[1].path
    └── 20241129_210033.mp4
```

---

## 4. HTTP API 仕様

### 4.1 ヘルスチェック

```
GET /health
```

**レスポンス（200 OK）**
```json
{ "status": "ok" }
```

**用途:** 親プロセスが定期的にポーリングして生存確認を行う。

---

### 4.2 動画一覧取得

```
GET /api/videos?folder=<フォルダパス>
```

**クエリパラメータ**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `folder` | string | — | `config.json` の `folders[].path` のいずれか。省略時は全フォルダを結合して返す |

**レスポンス（200 OK）**
```json
{
  "total": 3,
  "videos": [
    {
      "path": "通常録画/20241201_093012.mp4",
      "name": "20241201_093012.mp4",
      "folder": "通常録画",
      "size": 1234567890,
      "modified": 1733042400,
      "mime": "video/mp4"
    }
  ]
}
```

**レスポンスフィールド**

| フィールド | 型 | 説明 |
|---|---|---|
| `total` | number | 動画の総件数 |
| `videos` | array | 動画エントリの配列（更新日時の新しい順） |
| `videos[].path` | string | `video_dir` からの相対パス。`/video/` や `/download/` エンドポイントに渡す値 |
| `videos[].name` | string | ファイル名のみ |
| `videos[].folder` | string | 所属フォルダのパス |
| `videos[].size` | number | ファイルサイズ（バイト） |
| `videos[].modified` | number | 最終更新日時（Unix タイムスタンプ、秒） |
| `videos[].mime` | string | MIMEタイプ |

**エラーレスポンス**

| ステータス | 条件 |
|---|---|
| `403 Forbidden` | `config.json` の `folders` に含まれないフォルダを指定した場合（パストラバーサル防止） |

---

### 4.3 動画ストリーミング配信

```
GET /video/<path>
```

- `<path>` : `/api/videos` レスポンスの `videos[].path` の値（例: `通常録画/20241201_093012.mp4`）
- **HTTP Range Requests に対応**（`Accept-Ranges: bytes`）
- ブラウザの `<video>` タグによるシーク・部分取得が可能

**リクエストヘッダー（オプション）**
```
Range: bytes=0-1048575
```

**レスポンスヘッダー**
```
Content-Type: video/mp4
Content-Length: 1048576
Content-Range: bytes 0-1048575/1234567890
Accept-Ranges: bytes
```

**ステータスコード**

| コード | 条件 |
|---|---|
| `200 OK` | Range ヘッダーなし（全体取得） |
| `206 Partial Content` | Range ヘッダーあり（部分取得） |
| `403 Forbidden` | パストラバーサル攻撃の検知 |
| `404 Not Found` | ファイルが存在しない |
| `416 Range Not Satisfiable` | 不正な Range 値 |

---

### 4.4 動画ダウンロード

```
GET /download/<path>
```

- `/video/<path>` と同一の仕様だが、以下のヘッダーを追加
- `Content-Disposition: attachment; filename="<ファイル名>"`
- ブラウザはストリーミングではなくファイル保存ダイアログを表示する

---

### 4.5 静的ファイル配信

```
GET /              → index.html（SPA）
GET /static/style.css
GET /static/app.js
```

これらはすべてバイナリに内包されており、ディスク I/O は発生しない。

---

## 5. 対応動画フォーマット

| 拡張子 | MIME タイプ | 備考 |
|---|---|---|
| `.mp4` | `video/mp4` | 最も広くサポート |
| `.webm` | `video/webm` | Chrome/Firefox 推奨 |
| `.mov` | `video/quicktime` | Safari 対応 |
| `.mkv` | `video/x-matroska` | 一部ブラウザのみ |
| `.avi` | `video/x-msvideo` | 古い形式 |

上記以外の拡張子は一覧に表示されない（無視される）。

---

## 6. セキュリティ仕様

### パストラバーサル防止

すべての `/video/*` と `/download/*` リクエストに対して以下の検証を行う：

1. `video_dir` + リクエストパスを結合してフルパスを生成
2. `canonicalize()`（シンボリックリンクも解決）でパスを正規化
3. 正規化後のパスが `canonicalize(video_dir)` で始まることを確認
4. 確認できない場合は `403 Forbidden` を返す

```rust
// 実装イメージ
fn safe_path(base: &Path, rel: &str) -> Option<PathBuf> {
    let candidate = base.join(rel).canonicalize().ok()?;
    let base_canon = base.canonicalize().ok()?;
    candidate.starts_with(&base_canon).then_some(candidate)
}
```

### フォルダアクセス制限

`/api/videos?folder=<xxx>` に対して、`xxx` が `config.json` の `folders[].path` に含まれるかを検証する。未定義のフォルダは `403` を返す。

---

## 7. Python からの統合サンプルコード

```python
import subprocess
import signal
import urllib.request
import urllib.error
import time
import json
import os


class VideoViewer:
    """
    video-viewer プロセスを管理するクラス。
    親プロセスから起動・停止・ヘルスチェックを行う。
    """

    def __init__(
        self,
        binary_path: str,
        config_path: str,
        startup_timeout: float = 10.0,
    ):
        self.binary_path = binary_path
        self.config_path = config_path
        self.startup_timeout = startup_timeout
        self._proc: subprocess.Popen | None = None

        # config.json からポート番号を読み取る
        with open(config_path) as f:
            cfg = json.load(f)
        self.port = cfg.get("port", 8080)
        self.base_url = f"http://127.0.0.1:{self.port}"

    # ── 起動 ────────────────────────────────────────

    def start(self) -> None:
        """サーバーを起動し、"Listening on" が出力されるまで待機する。"""
        self._proc = subprocess.Popen(
            [self.binary_path, self.config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        deadline = time.monotonic() + self.startup_timeout
        for line in self._proc.stdout:
            if "Listening on" in line:
                return  # 起動完了
            if time.monotonic() > deadline:
                self.stop()
                raise TimeoutError("video-viewer の起動がタイムアウトしました")

        # プロセスが予期せず終了した場合
        stderr = self._proc.stderr.read()
        raise RuntimeError(f"video-viewer が起動失敗: {stderr}")

    # ── 停止 ────────────────────────────────────────

    def stop(self, grace_period: float = 10.0) -> None:
        """SIGTERM でグレースフルシャットダウンを要求する。"""
        if self._proc is None or self._proc.poll() is not None:
            return
        self._proc.send_signal(signal.SIGTERM)
        try:
            self._proc.wait(timeout=grace_period)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None

    # ── ヘルスチェック ───────────────────────────────

    def is_healthy(self, timeout: float = 2.0) -> bool:
        """GET /health が {"status":"ok"} を返すか確認する。"""
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/health", timeout=timeout
            ) as res:
                body = json.loads(res.read())
                return body.get("status") == "ok"
        except Exception:
            return False

    # ── 動画一覧取得 ────────────────────────────────

    def list_videos(self, folder: str | None = None) -> list[dict]:
        """
        動画の一覧を取得する。

        Args:
            folder: config.json の folders[].path の値。
                    None の場合は全フォルダを返す。

        Returns:
            動画エントリのリスト（更新日時の新しい順）
        """
        url = f"{self.base_url}/api/videos"
        if folder:
            url += f"?folder={urllib.parse.quote(folder)}"
        with urllib.request.urlopen(url, timeout=5.0) as res:
            return json.loads(res.read())["videos"]

    # ── URL 生成ヘルパー ─────────────────────────────

    def stream_url(self, video_path: str) -> str:
        """ストリーミング再生用 URL を返す。"""
        return f"{self.base_url}/video/{urllib.parse.quote(video_path)}"

    def download_url(self, video_path: str) -> str:
        """ダウンロード用 URL を返す。"""
        return f"{self.base_url}/download/{urllib.parse.quote(video_path)}"

    # ── コンテキストマネージャ ───────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None


# ── 使用例 ─────────────────────────────────────────

if __name__ == "__main__":
    import urllib.parse

    with VideoViewer(
        binary_path="/home/pi/video-viewer/video-viewer",
        config_path="/home/pi/video-viewer/config.json",
    ) as viewer:

        print(f"起動完了 (PID: {viewer.pid})")
        print(f"ヘルスチェック: {viewer.is_healthy()}")

        # 通常録画フォルダの一覧取得
        videos = viewer.list_videos(folder="通常録画")
        for v in videos:
            print(f"  {v['name']}  {v['size'] // 1024 // 1024} MB")
            print(f"    再生URL: {viewer.stream_url(v['path'])}")
            print(f"    DLURL:   {viewer.download_url(v['path'])}")

    print("停止完了")
```

---

## 8. Rust からの統合サンプルコード

```rust
use std::process::{Child, Command, Stdio};
use std::io::{BufRead, BufReader};
use std::time::{Duration, Instant};

pub struct VideoViewer {
    child: Child,
    pub port: u16,
}

impl VideoViewer {
    pub fn start(binary: &str, config: &str) -> Result<Self, Box<dyn std::error::Error>> {
        let mut child = Command::new(binary)
            .arg(config)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;

        // "Listening on" が出るまで待機
        let stdout = child.stdout.take().unwrap();
        let reader = BufReader::new(stdout);
        let deadline = Instant::now() + Duration::from_secs(10);

        for line in reader.lines() {
            let line = line?;
            if line.contains("Listening on") {
                return Ok(Self { child, port: 8080 });
            }
            if Instant::now() > deadline {
                let _ = child.kill();
                return Err("起動タイムアウト".into());
            }
        }
        Err("起動失敗".into())
    }

    pub fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    pub async fn is_healthy(&self) -> bool {
        reqwest::get(format!("{}/health", self.base_url()))
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false)
    }

    pub fn stop(&mut self) {
        unsafe { libc::kill(self.child.id() as i32, libc::SIGTERM); }
        let _ = self.child.wait();
    }
}

impl Drop for VideoViewer {
    fn drop(&mut self) { self.stop(); }
}
```

---

## 9. フロントエンド仕様（ブラウザ側）

### 画面構成（SPA、3画面）

| 画面ID | 役割 | 表示条件 |
|---|---|---|
| `screen-home` | フォルダ選択（トップ） | 初回表示・一覧の「戻る」押下時 |
| `screen-list` | 動画一覧 | フォルダカード押下時 |
| `screen-player` | 動画再生・DL | 動画行押下時 |

画面切り替えは `display: none / flex` の CSS クラス付け替えのみ（ページ遷移なし）。

### DOM 要素 ID 一覧（外部から操作する場合）

| ID | 要素 | 説明 |
|---|---|---|
| `folder-list` | `<div>` | フォルダカードが動的に追加されるコンテナ |
| `video-list` | `<div>` | 動画リストアイテムが動的に追加されるコンテナ |
| `player-video` | `<video>` | HTML5 動画プレーヤー本体 |
| `seek-bar` | `<input[range]>` | シークバー（0〜100） |
| `time-current` | `<span>` | 現在再生位置（`M:SS` 形式） |
| `time-total` | `<span>` | 動画の総時間（`M:SS` 形式） |
| `btn-play-pause` | `<button>` | 再生/一時停止トグルボタン |
| `btn-rewind` | `<button>` | 10秒戻るボタン |
| `btn-forward` | `<button>` | 10秒進むボタン |
| `btn-fullscreen` | `<button>` | 全画面ボタン |
| `player-folder-tag` | `<div>` | 所属フォルダ名タグ |
| `player-video-name` | `<div>` | 再生中ファイル名 |
| `player-video-meta` | `<div>` | サイズ・フォルダ名 |
| `player-download` | `<a>` | ダウンロードリンク |

### JavaScript グローバル変数・関数（外部から呼び出し可能）

```javascript
// 変数
currentFolder  // 現在選択中のフォルダオブジェクト { name, path, ... }
currentVideo   // 現在再生中の動画エントリ
videoEl        // <video> 要素への参照

// 関数
showScreen(id)              // 画面を切り替える
openFolder(folder)          // フォルダを開いて動画一覧を表示
openPlayer(video)           // 動画再生画面を開く
togglePlayPause()           // 再生/一時停止
skip(secs)                  // 指定秒数スキップ（負値で戻る）
toggleFullscreen()          // 全画面切り替え
downloadFile(path)          // ダウンロードを開始
```

---

## 10. ログ仕様

| ストリーム | 内容 | 形式例 |
|---|---|---|
| stdout | 起動完了メッセージ | `Listening on http://0.0.0.0:8080` |
| stdout | tracing ログ | `2024-12-01T03:18:45.210Z INFO video_viewer: Listening on http://0.0.0.0:8080` |
| stderr | エラー・警告 | `設定ファイル 'config.json' を読み込めません: No such file` |

ログレベルは環境変数 `RUST_LOG` で制御する：

```bash
RUST_LOG=info ./video-viewer config.json   # INFO以上を出力
RUST_LOG=debug ./video-viewer config.json  # デバッグログも出力
RUST_LOG=warn ./video-viewer config.json   # 警告以上のみ
```

---

## 11. パフォーマンス特性

| 指標 | 値 | 条件 |
|---|---|---|
| バイナリサイズ | 〜5MB | リリースビルド（`strip = true`） |
| 起動時間 | < 500ms | Raspberry Pi 5 |
| アイドルメモリ | 〜10MB | 動画フォルダ1000ファイル以下 |
| 動画配信スループット | Raspberry Pi 5 の NIC 上限 | ストリーミング時 |
| API レスポンス | < 50ms | 1000ファイル以下、キャッシュなし |

---

## 12. デプロイ手順

### Raspberry Pi 5 向けビルド（Mac/Linux からのクロスコンパイル）

```bash
# ターゲット追加（初回のみ）
rustup target add aarch64-unknown-linux-gnu

# macOS の場合、クロスリンカーのインストール（初回のみ）
brew install SergioBenitez/osxct/aarch64-unknown-linux-gnu

# ビルド
cargo build --release --target aarch64-unknown-linux-gnu

# ラズパイに転送して実行
scp target/aarch64-unknown-linux-gnu/release/video-viewer pi@raspberrypi.local:~/video-viewer/
scp config.json pi@raspberrypi.local:~/video-viewer/
```

### ワンコマンドデプロイ

```bash
./deploy.sh 192.168.1.100  # ラズパイのIPアドレスを指定
```

### systemd による自動起動

```bash
# ラズパイ上で実行
sudo cp video-viewer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable video-viewer
sudo systemctl start video-viewer
```

---

## 13. ファイル構成（完全版）

```
video-viewer/
├── Cargo.toml                  # Rust パッケージ定義・依存関係
├── Cargo.lock                  # 依存バージョンのロック
├── config.json                 # 実行時設定（video_dir・port・folders）
├── deploy.sh                   # ラズパイへのワンコマンドデプロイスクリプト
├── video-viewer.service        # systemd サービスユニットファイル
├── .cargo/
│   └── config.toml             # ARM64 クロスコンパイル用リンカー設定
├── src/
│   ├── main.rs                 # エントリポイント・ルーター・シャットダウン
│   ├── config.rs               # 設定ファイルのデシリアライズ
│   ├── scanner.rs              # 動画ファイルスキャン・パストラバーサル防止
│   └── handlers/
│       ├── mod.rs              # ハンドラーモジュール宣言
│       ├── videos.rs           # GET /api/videos
│       ├── stream.rs           # GET /video/* および GET /download/*
│       └── download.rs         # （将来拡張用予約）
├── static/
│   ├── index.html              # SPA HTML（3画面を1ファイルに収録）
│   ├── style.css               # ダークテーマ・レスポンシブ CSS
│   └── app.js                  # 画面制御・API通信・動画操作 JS
└── docs/
    ├── INTEGRATION.md          # 本ファイル（親プロセス統合ガイド）
    ├── REQUIREMENTS.md         # 要件定義書
    ├── DESIGN.md               # 設計書
    ├── API.md                  # API リファレンス
    ├── DEVELOPMENT.md          # 開発・ビルド手順
    ├── DECISIONS.md            # 技術選定記録（ADR）
    ├── PLAN.md                 # 実装計画書
    ├── UI_DESIGN.md            # UI 設計書
    └── EXPLANATION.md          # 初学者向け解説
```

---

## 14. バージョン履歴

| バージョン | 日付 | 内容 |
|---|---|---|
| v1.0.0 | 2026-06-24 | 初期リリース。フォルダ選択・動画一覧・ストリーミング再生・ダウンロード機能 |
