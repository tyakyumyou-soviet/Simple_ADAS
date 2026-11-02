'use strict';

const FOLDERS = [
  { name: '通常録画',   path: '通常録画',   artworkClass: 'artwork-normal', barClass: 'bar-normal', icon: '📹' },
  { name: 'イベント録画', path: 'イベント録画', artworkClass: 'artwork-event',  barClass: 'bar-event',  icon: '⚠️' },
];

let currentFolder = null;
let currentVideo = null;
let videoEl = null;

// ── 画面切り替え ─────────────────────────────
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  window.scrollTo(0, 0);
}

// ── フォーマット ──────────────────────────────
function fmtSize(bytes) {
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(0) + ' MB';
  return (bytes / 1e3).toFixed(0) + ' KB';
}

function fmtDate(unixSecs) {
  const d = new Date(unixSecs * 1000);
  return d.toLocaleDateString('ja-JP', { month: '2-digit', day: '2-digit' });
}

function fmtTime(secs) {
  if (isNaN(secs)) return '0:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ── 画面1: フォルダ選択 ───────────────────────
async function initHome() {
  const list = document.getElementById('folder-list');
  list.innerHTML = '';

  const counts = await Promise.all(
    FOLDERS.map(f =>
      fetch(`/api/videos?folder=${encodeURIComponent(f.path)}`)
        .then(r => r.json())
        .then(d => d.total)
        .catch(() => 0)
    )
  );

  FOLDERS.forEach((f, i) => {
    const btn = document.createElement('button');
    btn.className = 'folder-card';
    btn.innerHTML = `
      <div class="folder-accent-bar ${f.barClass}"></div>
      <div class="folder-card-inner">
        <div class="folder-artwork ${f.artworkClass}">
          <span class="artwork-icon">${f.icon}</span>
        </div>
        <div class="folder-info">
          <div class="folder-name">${f.name}</div>
          <div class="folder-count">${counts[i]}本の動画</div>
        </div>
        <span class="folder-chevron">›</span>
      </div>
    `;
    btn.addEventListener('click', () => openFolder(f));
    list.appendChild(btn);
  });
}

// ── 画面2: 動画一覧 ───────────────────────────
async function openFolder(folder) {
  currentFolder = folder;
  document.getElementById('folder-title').textContent = folder.name;
  const list = document.getElementById('video-list');
  list.innerHTML = '<div class="loading"><div class="spinner"></div><span>読み込み中...</span></div>';
  showScreen('screen-list');

  const res = await fetch(`/api/videos?folder=${encodeURIComponent(folder.path)}`);
  const data = await res.json();

  if (data.videos.length === 0) {
    list.innerHTML = '<div class="empty-msg">動画がありません</div>';
    return;
  }

  list.innerHTML = '';
  data.videos.forEach(v => {
    const item = document.createElement('div');
    item.className = 'video-item';
    item.innerHTML = `
      <div class="video-thumb">
        <div class="play-overlay"><span>▶</span></div>
      </div>
      <div class="video-body">
        <div class="video-name">${escHtml(v.name)}</div>
        <div class="video-meta">
          <span>${fmtSize(v.size)}</span>
          <span class="meta-dot">·</span>
          <span>${fmtDate(v.modified)}</span>
        </div>
      </div>
      <button class="btn-dl-item" aria-label="ダウンロード" data-path="${escAttr(v.path)}">⬇</button>
    `;
    item.querySelector('.video-body').addEventListener('click', () => openPlayer(v));
    item.querySelector('.video-thumb').addEventListener('click', () => openPlayer(v));
    item.querySelector('.btn-dl-item').addEventListener('click', e => {
      e.stopPropagation();
      downloadFile(v.path);
    });
    list.appendChild(item);
  });
}

// ── 画面3: 動画再生 ───────────────────────────
function openPlayer(video) {
  currentVideo = video;
  document.getElementById('player-title').textContent = video.name;
  document.getElementById('player-video-name').textContent = video.name;
  document.getElementById('player-video-meta').textContent =
    `${fmtSize(video.size)} · ${currentFolder.name}`;

  document.getElementById('player-folder-tag').textContent = '● ' + currentFolder.name;

  const dl = document.getElementById('player-download');
  dl.href = `/download/${encodeURIComponent(video.path)}`;
  dl.download = video.name;

  videoEl = document.getElementById('player-video');
  videoEl.src = `/video/${encodeURIComponent(video.path)}`;
  videoEl.load();

  updatePlayPauseIcon();
  document.getElementById('seek-bar').value = 0;
  document.getElementById('time-current').textContent = '0:00';
  document.getElementById('time-total').textContent = '0:00';

  showScreen('screen-player');
}

function updatePlayPauseIcon() {
  const btn = document.getElementById('btn-play-pause');
  btn.textContent = (videoEl && !videoEl.paused) ? '⏸' : '▶';
}

function togglePlayPause() {
  if (!videoEl) return;
  if (videoEl.paused) { videoEl.play(); } else { videoEl.pause(); }
}

function skip(secs) {
  if (!videoEl) return;
  videoEl.currentTime = Math.max(0, Math.min(videoEl.duration || 0, videoEl.currentTime + secs));
}

function toggleFullscreen() {
  if (!videoEl) return;
  if (videoEl.requestFullscreen) videoEl.requestFullscreen();
  else if (videoEl.webkitEnterFullscreen) videoEl.webkitEnterFullscreen();
}

function downloadFile(path) {
  const a = document.createElement('a');
  a.href = `/download/${encodeURIComponent(path)}`;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s) { return escHtml(s); }

// ── イベント登録 ──────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // 戻るボタン
  document.getElementById('btn-back-list').addEventListener('click', () => {
    if (videoEl) { videoEl.pause(); videoEl.src = ''; }
    showScreen('screen-home');
    initHome();
  });
  document.getElementById('btn-back-player').addEventListener('click', () => {
    if (videoEl) { videoEl.pause(); videoEl.src = ''; }
    openFolder(currentFolder);
  });

  // 再生コントロール
  document.getElementById('btn-rewind').addEventListener('click', () => skip(-10));
  document.getElementById('btn-play-pause').addEventListener('click', togglePlayPause);
  document.getElementById('btn-forward').addEventListener('click', () => skip(10));
  document.getElementById('btn-fullscreen').addEventListener('click', toggleFullscreen);

  // 動画タップで再生/停止
  document.getElementById('player-video').addEventListener('click', togglePlayPause);

  // 動画イベント
  const video = document.getElementById('player-video');
  video.addEventListener('play',  updatePlayPauseIcon);
  video.addEventListener('pause', updatePlayPauseIcon);
  video.addEventListener('timeupdate', () => {
    const seek = document.getElementById('seek-bar');
    const cur  = document.getElementById('time-current');
    if (video.duration) {
      const pct = (video.currentTime / video.duration) * 100;
      seek.value = pct;
      seek.style.setProperty('--progress', pct + '%');
    }
    cur.textContent = fmtTime(video.currentTime);
  });
  video.addEventListener('loadedmetadata', () => {
    document.getElementById('time-total').textContent = fmtTime(video.duration);
  });

  // シークバー
  document.getElementById('seek-bar').addEventListener('input', e => {
    if (video.duration) {
      video.currentTime = (e.target.value / 100) * video.duration;
    }
  });

  // 起動
  showScreen('screen-home');
  initHome();
});
