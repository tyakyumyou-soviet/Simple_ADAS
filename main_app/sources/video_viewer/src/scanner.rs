use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

#[derive(Debug, Serialize, Clone)]
pub struct VideoEntry {
    pub path: String,
    pub name: String,
    pub folder: String,
    pub size: u64,
    pub modified: u64,
    pub mime: &'static str,
}

const VIDEO_EXTENSIONS: &[(&str, &str)] = &[
    ("mp4", "video/mp4"),
    ("webm", "video/webm"),
    ("mov", "video/quicktime"),
    ("mkv", "video/x-matroska"),
    ("avi", "video/x-msvideo"),
];

fn mime_for_ext(ext: &str) -> Option<&'static str> {
    VIDEO_EXTENSIONS
        .iter()
        .find(|(e, _)| *e == ext)
        .map(|(_, m)| *m)
}

pub fn scan_folder(base_dir: &Path, folder_path: &str) -> Vec<VideoEntry> {
    let dir = base_dir.join(folder_path);
    let mut entries = Vec::new();
    collect_videos(base_dir, &dir, folder_path, &mut entries);
    entries.sort_by(|a, b| b.modified.cmp(&a.modified));
    entries
}

fn collect_videos(base_dir: &Path, dir: &Path, folder_path: &str, entries: &mut Vec<VideoEntry>) {
    let read_dir = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(e) => {
            tracing::warn!("フォルダ読み込みエラー {:?}: {}", dir, e);
            return;
        }
    };

    for entry in read_dir.flatten() {
        let path = entry.path();
        let file_type = match entry.file_type() {
            Ok(file_type) => file_type,
            Err(_) => continue,
        };
        if file_type.is_dir() {
            collect_videos(base_dir, &path, folder_path, entries);
            continue;
        }
        if !file_type.is_file() {
            continue;
        }

        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .map(str::to_lowercase);
        let mime = match ext.as_deref().and_then(mime_for_ext) {
            Some(m) => m,
            None => continue,
        };
        let name = match path.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let relative_path = match path.strip_prefix(base_dir) {
            Ok(relative) => relative.to_string_lossy().replace('\\', "/"),
            Err(_) => continue,
        };
        let meta = match std::fs::metadata(&path) {
            Ok(m) => m,
            Err(_) => continue,
        };
        let modified = meta
            .modified()
            .unwrap_or(SystemTime::UNIX_EPOCH)
            .duration_since(SystemTime::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        entries.push(VideoEntry {
            path: relative_path,
            name,
            folder: folder_path.to_string(),
            size: meta.len(),
            modified,
            mime,
        });
    }
}

pub fn safe_path(base: &Path, rel: &str) -> Option<PathBuf> {
    let candidate = base.join(rel);
    let canonical_candidate = candidate.canonicalize().ok()?;
    let canonical_base = base.canonicalize().ok()?;
    if canonical_candidate.starts_with(&canonical_base) {
        Some(canonical_candidate)
    } else {
        None
    }
}
