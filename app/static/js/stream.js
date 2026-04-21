/**
 * stream.js — WebSocket video client + status polling + feature toggles
 *
 * Architecture:
 *  - /ws/video  → binary JPEG frames rendered onto #video-canvas
 *  - /ws/events → JSON event stream (zone alarms etc.)
 *  - /api/status polled every 2s for FPS and connection health
 *  - /api/config PUT to toggle features at runtime
 */

const videoCanvas = document.getElementById('video-canvas');
const zoneCanvas  = document.getElementById('zone-canvas');
const ctx         = videoCanvas.getContext('2d');

const connDot     = document.getElementById('conn-indicator');
const connLabel   = document.getElementById('conn-label');
const fpsCounter  = document.getElementById('fps-counter');
const clientCount = document.getElementById('client-count');
const streamSrc   = document.getElementById('stream-source');

// ── Video WebSocket ──────────────────────────────────────────────────────────

let videoWs = null;
let reconnectTimer = null;

function connectVideo() {
  clearTimeout(reconnectTimer);
  const url = `ws://${location.host}/ws/video`;
  videoWs = new WebSocket(url);
  videoWs.binaryType = 'arraybuffer';

  videoWs.onopen = () => {
    setConnected(true);
  };

  videoWs.onclose = () => {
    setConnected(false);
    reconnectTimer = setTimeout(connectVideo, 2000);
  };

  videoWs.onerror = () => {
    videoWs.close();
  };

  videoWs.onmessage = (event) => {
    if (!(event.data instanceof ArrayBuffer) || event.data.byteLength === 0) return;
    renderFrame(event.data);
  };
}

function renderFrame(buffer) {
  const blob = new Blob([buffer], { type: 'image/jpeg' });
  const url  = URL.createObjectURL(blob);
  const img  = new Image();

  img.onload = () => {
    if (videoCanvas.width !== img.width || videoCanvas.height !== img.height) {
      videoCanvas.width  = img.width;
      videoCanvas.height = img.height;
      zoneCanvas.width   = img.width;
      zoneCanvas.height  = img.height;
    }
    ctx.drawImage(img, 0, 0);
    URL.revokeObjectURL(url);
  };

  img.src = url;
}

function setConnected(connected) {
  connDot.className   = `dot ${connected ? 'connected' : 'disconnected'}`;
  connLabel.textContent = connected ? 'Connected' : 'Disconnected — retrying…';
}

// ── Event WebSocket ───────────────────────────────────────────────────────────

let eventWs = null;

function connectEvents() {
  const url = `ws://${location.host}/ws/events`;
  eventWs = new WebSocket(url);

  eventWs.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      handleEvent(payload);
    } catch (_) {}
  };

  eventWs.onclose = () => setTimeout(connectEvents, 3000);
}

function handleEvent(payload) {
  // Handled by notifications.js
  window.dispatchEvent(new CustomEvent('vip:event', { detail: payload }));
}

// ── Status polling ────────────────────────────────────────────────────────────

async function pollStatus() {
  try {
    const res  = await fetch('/api/status');
    const data = await res.json();

    fpsCounter.textContent  = `${data.actual_fps} fps`;
    clientCount.textContent = `${data.video_clients} client${data.video_clients !== 1 ? 's' : ''}`;
    streamSrc.textContent   = data.source;
  } catch (_) {}
}

document.getElementById('btn-reconnect').addEventListener('click', () => {
  if (videoWs) videoWs.close();
});

// ── Init ──────────────────────────────────────────────────────────────────────

connectVideo();
connectEvents();
setInterval(pollStatus, 2000);
pollStatus();
