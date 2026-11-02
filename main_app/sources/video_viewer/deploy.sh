#!/bin/bash
# Raspberry Pi 5 へのデプロイスクリプト
# 使い方: ./deploy.sh <ラズパイのIPアドレス>
# 例:     ./deploy.sh 192.168.1.100

set -e

PI_HOST="${1:-raspberrypi.local}"
PI_USER="pi"
REMOTE_DIR="/home/pi/video-viewer"

echo "==> ARM64向けリリースビルド..."
cargo build --release --target aarch64-unknown-linux-gnu

echo "==> ラズパイにファイルを転送..."
ssh "${PI_USER}@${PI_HOST}" "mkdir -p ${REMOTE_DIR}"
scp target/aarch64-unknown-linux-gnu/release/video-viewer "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/"
scp config.json "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/"

echo "==> systemd サービスを設定..."
scp video-viewer.service "${PI_USER}@${PI_HOST}:/tmp/"
ssh "${PI_USER}@${PI_HOST}" "sudo mv /tmp/video-viewer.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable video-viewer && sudo systemctl restart video-viewer"

echo "==> 完了！"
echo "    ブラウザで http://${PI_HOST}:8080 を開いてください"
