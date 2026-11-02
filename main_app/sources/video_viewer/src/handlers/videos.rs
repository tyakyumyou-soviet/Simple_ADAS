use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::{config::Config, scanner::scan_folder};

#[derive(Deserialize)]
pub struct VideosQuery {
    pub folder: Option<String>,
}

#[derive(Serialize)]
pub struct VideosResponse {
    pub total: usize,
    pub videos: Vec<crate::scanner::VideoEntry>,
}

pub async fn list_videos(
    State(config): State<Arc<Config>>,
    Query(params): Query<VideosQuery>,
) -> Result<Json<VideosResponse>, StatusCode> {
    let folder = params.folder.as_deref().unwrap_or("");

    if !folder.is_empty() {
        let allowed = config
            .folders
            .iter()
            .any(|f| f.path == folder);
        if !allowed {
            return Err(StatusCode::FORBIDDEN);
        }
    }

    let videos = if folder.is_empty() {
        let mut all = Vec::new();
        for f in &config.folders {
            all.extend(scan_folder(&config.video_dir, &f.path));
        }
        all.sort_by(|a, b| b.modified.cmp(&a.modified));
        all
    } else {
        scan_folder(&config.video_dir, folder)
    };

    let total = videos.len();
    Ok(Json(VideosResponse { total, videos }))
}
