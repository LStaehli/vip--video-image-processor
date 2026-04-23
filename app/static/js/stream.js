/**
 * stream.js — WebSocket video client + status polling + stream tab switching
 *
 * Architecture:
 *  - /ws/video/{stream_id}  → binary JPEG frames rendered onto #video-canvas
 *  - /ws/events/{stream_id} → JSON event stream (zone alarms etc.)
 *  - /api/status?stream_id= polled every 2s for FPS and connection health
 *  - /api/streams           fetched on load to render tab bar
 */

const videoCanvas = document.getElementById('video-canvas');
const zoneCanvas  = document.getElementById('zone-canvas');
const ctx         = videoCanvas.getContext('2d');

const connDot     = document.getElementById('conn-indicator');
const connLabel   = document.getElementById('conn-label');
const fpsCounter  = document.getElementById('fps-counter');
const clientCount = document.getElementById('client-count');
const streamSrc   = document.getElementById('stream-source');
const streamTabs  = document.getElementById('stream-tabs');

// ── Active stream state ──────────────────────────────────────────────────────

let activeStreamId = null;
window.activeStreamId = null;  // exposed for controls.js recording calls
let _loadedStreams = [];        // kept in sync by loadStreamTabs for URL resolution

// ── Video WebSocket ──────────────────────────────────────────────────────────

let videoWs = null;
let reconnectTimer = null;

function connectVideo() {
  clearTimeout(reconnectTimer);
  const path = activeStreamId ? `/ws/video/${activeStreamId}` : '/ws/video';
  const url = `ws://${location.host}${path}`;
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
  connDot.className     = `dot ${connected ? 'connected' : 'disconnected'}`;
  connLabel.textContent = connected ? 'Connected' : 'Disconnected — retrying…';
}

// ── Event WebSocket ───────────────────────────────────────────────────────────

let eventWs = null;

function connectEvents() {
  const path = activeStreamId ? `/ws/events/${activeStreamId}` : '/ws/events';
  const url = `ws://${location.host}${path}`;
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
  window.dispatchEvent(new CustomEvent('vip:event', { detail: payload }));
}

// ── Status polling ────────────────────────────────────────────────────────────

async function pollStatus() {
  try {
    const url  = activeStreamId ? `/api/status?stream_id=${activeStreamId}` : '/api/status';
    const res  = await fetch(url);
    const data = await res.json();

    fpsCounter.textContent  = `${data.actual_fps} fps`;
    clientCount.textContent = `${data.video_clients} client${data.video_clients !== 1 ? 's' : ''}`;
    streamSrc.textContent   = data.source;
  } catch (_) {}
}

// ── Stream tab switching ──────────────────────────────────────────────────────

function switchStream(streamId) {
  if (streamId === activeStreamId) return;
  activeStreamId = streamId;
  window.activeStreamId = streamId;

  // Reflect active channel in the URL without triggering a reload
  const stream = _loadedStreams.find(s => s.id === streamId);
  if (stream) {
    history.replaceState(null, '', `?channel=${stream.channel_number}`);
  }

  // Update tab active state
  streamTabs.querySelectorAll('.stream-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.streamId == streamId);
  });

  // Reconnect both sockets to the new stream
  if (videoWs) { clearTimeout(reconnectTimer); videoWs.onclose = null; videoWs.close(); }
  if (eventWs) { eventWs.onclose = null; eventWs.close(); }

  connectVideo();
  connectEvents();
  pollStatus();

  // Reload per-stream data
  window.loadConfig?.();      // sidebar controls (motion, detection, faces…)
  window.loadZoneConfig?.();  // zone toggle + stop-mode radios
  window.loadZones?.();       // zone list in sidebar
}

function renderStreamTabs(streams) {
  streamTabs.innerHTML = '';
  // Only show the tab bar when there is more than one stream
  if (streams.length <= 1) return;

  streams.forEach(s => {
    const btn = document.createElement('button');
    btn.className = 'stream-tab';
    btn.dataset.streamId = s.id;
    btn.textContent = `CH${s.channel_number} · ${s.name}`;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', s.id === activeStreamId);
    btn.addEventListener('click', () => switchStream(s.id));
    streamTabs.appendChild(btn);
  });

  // Highlight current
  streamTabs.querySelectorAll('.stream-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.streamId == activeStreamId);
  });
}

async function loadStreamTabs() {
  try {
    const res  = await fetch('/api/streams');
    const data = await res.json();
    // Only show streams that are enabled (have an active pipeline)
    const running = (data.streams ?? []).filter(s => s.enabled !== false);
    _loadedStreams = running;

    // On first load, honour ?channel=N from the URL; fall back to first stream
    if (!activeStreamId && running.length > 0) {
      const urlChannel = parseInt(new URLSearchParams(location.search).get('channel'));
      const preferred  = urlChannel ? running.find(s => s.channel_number === urlChannel) : null;
      const initial    = preferred ?? running[0];
      activeStreamId        = initial.id;
      window.activeStreamId = initial.id;
      // Normalise the URL in case the param was absent or pointed to a missing channel
      history.replaceState(null, '', `?channel=${initial.channel_number}`);
    }

    renderStreamTabs(running);
  } catch (_) {}
}

document.getElementById('btn-reconnect').addEventListener('click', () => {
  if (videoWs) videoWs.close();
});

// ── Init ──────────────────────────────────────────────────────────────────────

window.loadStreamTabs = loadStreamTabs;

loadStreamTabs().then(() => {
  connectVideo();
  connectEvents();
  setInterval(pollStatus, 2000);
  pollStatus();
  window.loadConfig?.();
  window.loadZoneConfig?.();
  window.loadZones?.();
});
