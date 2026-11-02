# API リファレンス

ベース URL: `http://<raspberry-pi-ip>:8080`

---

## GET /health

サーバーの死活確認。親システムのヘルスチェックに使用する。

**レスポンス** `200 OK`
```json
{ "status": "ok", "uptime_secs": 123 }
```

---

## GET /api/videos

動画ファイルの一覧を返す。

**クエリパラメータ**

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `search` | string | — | ファイル名の部分一致フィルタ |
| `sort` | `name` \| `modified` \| `size` | `modified` | ソートキー |
| `order` | `asc` \| `desc` | `desc` | ソート順 |
| `folder` | string | — | サブフォルダでの絞り込み（相対パス） |

**レスポンス** `200 OK`
```json
{
  "total": 42,
  "videos": [
    {
      "path": "subfolder/video.mp4",
      "name": "video.mp4",
      "size": 1234567890,
      "modified": "2025-06-01T12:00:00Z",
      "mime": "video/mp4",
      "duration_secs": null
    }
  ]
}
```

---

## GET /video/*path

動画をストリーミング配信する。HTTP Range Requests に対応。

**パラメータ**
- `path`: `video_dir` からの相対パス（例: `subfolder/video.mp4`）

**リクエストヘッダー（オプション）**
```
Range: bytes=0-1023
```

**レスポンス**

| 条件 | ステータス | 説明 |
|---|---|---|
| Range なし | `200 OK` | ファイル全体 |
| Range あり | `206 Partial Content` | 指定範囲のみ |
| ファイルなし | `404 Not Found` | — |
| パストラバーサル | `403 Forbidden` | — |

**レスポンスヘッダー**
```
Content-Type: video/mp4
Content-Length: 1024
Content-Range: bytes 0-1023/1234567890
Accept-Ranges: bytes
```

---

## GET /download/*path

動画ファイルをダウンロードする。

`/video/*path` と同一だが、以下のヘッダーを追加:
```
Content-Disposition: attachment; filename="video.mp4"
```

---

## GET /thumb/*path

動画のサムネイル画像を返す（ffmpeg が利用可能な場合のみ）。

**レスポンス** `200 OK`
```
Content-Type: image/jpeg
```

ffmpeg が存在しない場合: `501 Not Implemented`

---

## エラーレスポンス

すべてのエラーは以下の形式:

```json
{ "error": "エラーメッセージ" }
```

| ステータス | 意味 |
|---|---|
| `400` | リクエスト不正 |
| `403` | アクセス禁止（パストラバーサル） |
| `404` | ファイルが存在しない |
| `500` | サーバー内部エラー |
| `501` | 機能未実装（ffmpeg なし等） |
