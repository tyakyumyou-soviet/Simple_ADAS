mod config;
mod handlers;
mod scanner;

use axum::{
    extract::State,
    http::{header, StatusCode},
    response::{Html, Json, Response},
    routing::get,
    Router,
};
use config::Config;
use serde_json::json;
use std::sync::Arc;
use tokio::signal;

use handlers::stream::{download_video, stream_video};
use handlers::videos::list_videos;

const INDEX_HTML: &str = include_str!("../static/index.html");
const STYLE_CSS: &str  = include_str!("../static/style.css");
const APP_JS: &str     = include_str!("../static/app.js");

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("video_viewer=info".parse().unwrap()),
        )
        .init();

    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "config.json".to_string());

    let config = match Config::load(&config_path) {
        Ok(c) => Arc::new(c),
        Err(e) => {
            eprintln!("設定ファイルの読み込みに失敗: {}", e);
            std::process::exit(1);
        }
    };

    let app = Router::new()
        .route("/", get(index))
        .route("/health", get(health))
        .route("/static/style.css", get(serve_css))
        .route("/static/app.js", get(serve_js))
        .route("/api/videos", get(list_videos))
        .route("/video/*path", get(stream_video))
        .route("/download/*path", get(download_video))
        .with_state(config.clone());

    let addr = format!("{}:{}", config.host, config.port);
    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();

    tracing::info!("Listening on http://{}", addr);
    println!("Listening on http://{}", addr);

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .unwrap();

    tracing::info!("サーバーを停止しました");
}

async fn index() -> Html<&'static str> {
    Html(INDEX_HTML)
}

async fn serve_css() -> Response<axum::body::Body> {
    Response::builder()
        .header(header::CONTENT_TYPE, "text/css; charset=utf-8")
        .body(axum::body::Body::from(STYLE_CSS))
        .unwrap()
}

async fn serve_js() -> Response<axum::body::Body> {
    Response::builder()
        .header(header::CONTENT_TYPE, "application/javascript; charset=utf-8")
        .body(axum::body::Body::from(APP_JS))
        .unwrap()
}

async fn health() -> Json<serde_json::Value> {
    Json(json!({ "status": "ok" }))
}

async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c().await.expect("Ctrl+C ハンドラーの設定に失敗");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("SIGTERM ハンドラーの設定に失敗")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    tracing::info!("シャットダウン信号を受信しました");
}
