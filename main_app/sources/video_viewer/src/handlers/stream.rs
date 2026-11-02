use axum::{
    body::Body,
    extract::{Path, State},
    http::{header, HeaderMap, StatusCode},
    response::Response,
};
use futures_util::stream;
use std::sync::Arc;
use tokio::fs::File;
use tokio::io::{AsyncReadExt, AsyncSeekExt};

const CHUNK_SIZE: usize = 64 * 1024;

use crate::{config::Config, scanner::safe_path};

pub async fn stream_video(
    State(config): State<Arc<Config>>,
    Path(rel_path): Path<String>,
    headers: HeaderMap,
) -> Result<Response<Body>, StatusCode> {
    serve_file(&config, &rel_path, &headers, false).await
}

pub async fn download_video(
    State(config): State<Arc<Config>>,
    Path(rel_path): Path<String>,
    headers: HeaderMap,
) -> Result<Response<Body>, StatusCode> {
    serve_file(&config, &rel_path, &headers, true).await
}

async fn serve_file(
    config: &Config,
    rel_path: &str,
    headers: &HeaderMap,
    as_download: bool,
) -> Result<Response<Body>, StatusCode> {
    let file_path = safe_path(&config.video_dir, rel_path).ok_or(StatusCode::FORBIDDEN)?;

    let file_size = tokio::fs::metadata(&file_path)
        .await
        .map_err(|_| StatusCode::NOT_FOUND)?
        .len();

    let file_name = file_path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("video");

    let ext = file_path
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_lowercase());
    let mime = mime_for_ext(ext.as_deref().unwrap_or("")).unwrap_or("application/octet-stream");

    let range_header = headers.get(header::RANGE).and_then(|v| v.to_str().ok());

    if file_size == 0 {
        return Err(StatusCode::NOT_FOUND);
    }
    let (start, end, status) = if let Some(range) = range_header {
        match parse_range(range, file_size) {
            Some((s, e)) => (s, e, StatusCode::PARTIAL_CONTENT),
            None => return Err(StatusCode::RANGE_NOT_SATISFIABLE),
        }
    } else {
        (0, file_size - 1, StatusCode::OK)
    };

    let length = end - start + 1;

    let mut file = File::open(&file_path)
        .await
        .map_err(|_| StatusCode::NOT_FOUND)?;

    if start > 0 {
        file.seek(std::io::SeekFrom::Start(start))
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    }

    // Read only a bounded chunk per poll instead of allocating the whole video.
    let chunks = stream::try_unfold((file, length), |(mut file, remaining)| async move {
        if remaining == 0 {
            return Ok::<_, std::io::Error>(None);
        }
        let mut buf = vec![0u8; remaining.min(CHUNK_SIZE as u64) as usize];
        let read = file.read(&mut buf).await?;
        if read == 0 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::UnexpectedEof,
                "video was truncated during transfer",
            ));
        }
        buf.truncate(read);
        Ok(Some((buf, (file, remaining - read as u64))))
    });

    let mut builder = Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, mime)
        .header(header::CONTENT_LENGTH, length.to_string())
        .header(header::ACCEPT_RANGES, "bytes")
        .header(
            header::CONTENT_RANGE,
            format!("bytes {}-{}/{}", start, end, file_size),
        );

    if as_download {
        builder = builder.header(
            header::CONTENT_DISPOSITION,
            format!("attachment; filename=\"{}\"", file_name),
        );
    }

    builder
        .body(Body::from_stream(chunks))
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)
}

fn parse_range(range: &str, file_size: u64) -> Option<(u64, u64)> {
    let range = range.strip_prefix("bytes=")?;
    let parts: Vec<&str> = range.splitn(2, '-').collect();
    if parts.len() != 2 {
        return None;
    }
    let start: u64 = parts[0].parse().ok()?;
    let end: u64 = if parts[1].is_empty() {
        file_size - 1
    } else {
        parts[1].parse().ok()?
    };
    if start > end || end >= file_size {
        return None;
    }
    Some((start, end))
}

fn mime_for_ext(ext: &str) -> Option<&'static str> {
    match ext {
        "mp4" => Some("video/mp4"),
        "webm" => Some("video/webm"),
        "mov" => Some("video/quicktime"),
        "mkv" => Some("video/x-matroska"),
        "avi" => Some("video/x-msvideo"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[tokio::test]
    async fn streams_large_video_and_requested_range() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir =
            std::env::temp_dir().join(format!("video-viewer-{}-{unique}", std::process::id()));
        std::fs::create_dir(&dir).unwrap();
        let data: Vec<u8> = (0..CHUNK_SIZE * 3 + 19).map(|i| (i % 251) as u8).collect();
        std::fs::write(dir.join("test.mp4"), &data).unwrap();
        let config = Config {
            video_dir: dir.clone(),
            port: 8080,
            host: "127.0.0.1".into(),
            folders: vec![],
        };

        let response = serve_file(&config, "test.mp4", &HeaderMap::new(), false)
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            axum::body::to_bytes(response.into_body(), data.len())
                .await
                .unwrap()
                .as_ref(),
            data
        );

        let mut headers = HeaderMap::new();
        headers.insert(header::RANGE, "bytes=65530-131080".parse().unwrap());
        let response = serve_file(&config, "test.mp4", &headers, true)
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::PARTIAL_CONTENT);
        assert_eq!(
            axum::body::to_bytes(response.into_body(), data.len())
                .await
                .unwrap()
                .as_ref(),
            &data[65530..=131080]
        );
        std::fs::remove_dir_all(dir).unwrap();
    }
}
