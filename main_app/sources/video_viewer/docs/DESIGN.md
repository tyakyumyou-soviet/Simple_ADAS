# 設計書

## 1. アーキテクチャ概要

```
┌─────────────────────────────────────────┐
│  親システム (Python / Rust)               │
│  subprocess として video-viewer を制御    │
└────────────────┬────────────────────────┘
                 │ SIGTERM / stdout 監視
                 ▼
┌─────────────────────────────────────────┐
│  video-viewer (Rust + Axum)             │
│                                         │
│  ┌─────────┐  ┌──────────┐  ┌────────┐ │
│  │ Router  │  │ Scanner  │  │ Config │ │
│  │ (Axum)  │  │ (tokio)  │  │ (JSON) │ │
│  └────┬────┘  └────┬─────┘  └────────┘ │
│       │            │                    │
│  ┌────▼────────────▼──────────────────┐ │
│  │           Handler Layer            │ │
│  │  /api/videos  /video/:p  /health   │ │
│  └────────────────────────────────────┘ │
└──────────────────────┬──────────────────┘
                       │ HTTP
                 ┌─────▼─────┐
                 │  Browser  │
                 │ (スマホ)   │
                 └───────────┘
                 
          ┌──────────────────┐
          │  ローカルフォルダ  │
          │  /path/to/videos │
          └──────────────────┘
```

---

## 2. 技術スタック

| 層 | 技術 | 選定理由 |
|---|---|---|
| HTTP サーバー | Axum 0.7 | tokio ベース・高速・エルゴノミクスが良い |
| 非同期ランタイム | Tokio | Rust 標準的な非同期ランタイム |
| シリアライズ | serde_json | 標準的・高速 |
| ファイル監視 | notify (オプション) | フォルダ変更検知 |
| 設定 | serde + JSON | 外部依存最小 |
| フロントエンド | Vanilla HTML/CSS/JS | ゼロ依存・転送量最小 |
| 静的ファイル | `include_str!` / tower-http | バイナリ内包 |

### Cargo.toml 依存関係

```toml
[dependencies]
axum = "0.7"
tokio = { version = "1", features = ["full"] }
tower-http = { version = "0.5", features = ["fs", "cors"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
notify = "6"          # オプション: フォルダ監視
tracing = "0.1"
tracing-subscriber = "0.3"
```

---

## 3. モジュール設計

### 3.1 `config.rs` — 設定

```rust
struct Config {
    video_dir: PathBuf,   // 動画フォルダのパス
    port: u16,            // デフォルト 8080
    thumbnail_dir: Option<PathBuf>,  // サムネイルキャッシュ先
    auth: Option<BasicAuth>,         // オプション認証
}
```

設定ファイル (`config.json`) 例:
```json
{
  "video_dir": "/home/pi/videos",
  "port": 8080,
  "thumbnail_dir": "/home/pi/.cache/video-viewer/thumbs"
}
```

CLI 引数 `--config <path>` で指定。デフォルトは `./config.json`。

---

### 3.2 `scanner.rs` — ファイルスキャン

- 起動時に `video_dir` を再帰スキャンしてメモリ内キャッシュ（`Arc<RwLock<Vec<VideoEntry>>>`）を構築
- `VideoEntry` は `{path, name, size, modified, mime_type}` を保持
- オプション: `notify` クレートでファイル変更を検知し、キャッシュを自動更新

```rust
struct VideoEntry {
    path: PathBuf,
    name: String,
    size: u64,
    modified: SystemTime,
    mime_type: &'static str,
}
```

対応 MIME タイプ:
| 拡張子 | MIME |
|---|---|
| .mp4 | video/mp4 |
| .webm | video/webm |
| .mov | video/quicktime |
| .mkv | video/x-matroska |
| .avi | video/x-msvideo |

---

### 3.3 `handlers/videos.rs` — 一覧 API

- `GET /api/videos?search=<q>&sort=<field>&folder=<f>` → JSON
- キャッシュから読み取り（ロックは短時間）
- クエリパラメータでフィルタ・ソート（サーバーサイド）

---

### 3.4 `handlers/stream.rs` — 動画ストリーミング

**HTTP Range Requests 対応が必須**（ブラウザのシーク動作に必要）

処理フロー:
1. パスをデコードし、`video_dir` からの相対パスとして検証（パストラバーサル防止）
2. `Range` ヘッダーを解析
3. ファイルを `tokio::fs::File` で開き、`Range` 位置にシーク
4. `Content-Range`, `Content-Length`, `Accept-Ranges: bytes` ヘッダーを付与
5. `206 Partial Content` または `200 OK` で応答
6. `io::copy` で逐次転送（メモリにファイル全体を読み込まない）

---

### 3.5 `handlers/download.rs` — ダウンロード

- `stream.rs` と同じロジック + `Content-Disposition: attachment; filename="<name>"` ヘッダーを追加

---

## 4. ルーティング

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/` | SPA HTML を返す |
| GET | `/health` | `{"status":"ok"}` を返す |
| GET | `/api/videos` | 動画一覧 JSON |
| GET | `/video/*path` | Range 対応ストリーミング |
| GET | `/download/*path` | ファイルダウンロード |
| GET | `/thumb/*path` | サムネイル画像（オプション） |

---

## 5. フロントエンド設計

### ページ構成（SPA・シングルHTML）

```
┌────────────────────────────────┐
│ [🔍 検索バー]     [≡ フォルダ] │  ← ヘッダー（固定）
├────────────────────────────────┤
│ [動画] [動画] [動画]           │
│ [動画] [動画] [動画]           │  ← グリッド一覧（スクロール）
│ ...                            │
└────────────────────────────────┘

タップ時 → 動画プレーヤー画面
┌────────────────────────────────┐
│ [← 戻る]                       │
│                                │
│   ┌──────────────────────┐    │
│   │   <video> プレーヤー  │    │
│   └──────────────────────┘    │
│                                │
│   ファイル名.mp4  1.2GB        │
│   [▶ 再生]  [⬇ ダウンロード]   │
└────────────────────────────────┘
```

### CSS 方針

- CSS Grid でレスポンシブグリッド（`auto-fill, minmax(160px, 1fr)`）
- タッチ操作最適化（`min-height: 44px` タップ領域）
- ダークモード対応（`prefers-color-scheme`）
- フォント: システムフォント（外部読み込みなし）

### JS 方針

- フレームワーク・バンドラー不使用
- `fetch` API で `/api/videos` を取得
- `history.pushState` で擬似ルーティング
- 総量 5KB 以下を目標

---

## 6. セキュリティ設計

### パストラバーサル防止

```rust
fn safe_path(base: &Path, user_input: &str) -> Option<PathBuf> {
    let candidate = base.join(user_input);
    let canonical = candidate.canonicalize().ok()?;
    if canonical.starts_with(base.canonicalize().ok()?) {
        Some(canonical)
    } else {
        None  // base 外へのアクセスは拒否
    }
}
```

### CORS

- デフォルトは同一オリジンのみ許可
- 設定で LAN サブネット許可を追加可能

---

## 7. グレースフルシャットダウン

```rust
// SIGTERM / Ctrl+C を受けたら新規接続を停止し、
// 進行中の転送が完了するまで最大 30 秒待機
tokio::select! {
    _ = server => {},
    _ = shutdown_signal() => {
        println!("Shutting down...");
    }
}
```

---

## 8. パフォーマンス設計

| 技法 | 効果 |
|---|---|
| スキャン結果を `Arc<RwLock>` でキャッシュ | 一覧 API が O(1) |
| `tokio::fs` で非同期 I/O | スレッドブロックなし |
| `io::copy` ストリーミング | メモリにファイルを全展開しない |
| 静的ファイルをバイナリ内包 | ファイル I/O ゼロ |
| `tower-http` の `CompressionLayer` | JSON レスポンスを gzip |
