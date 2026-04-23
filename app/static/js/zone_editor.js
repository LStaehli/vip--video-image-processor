/**
 * zone_editor.js — Detection zone drawing and management
 *
 * NOTE: zoneCanvas is already declared by stream.js — do NOT re-declare it here.
 *
 * All zone API calls are stream-scoped: /api/streams/{activeStreamId}/zones
 *
 * UX:
 *  - Toggle switch enables/disables the ZoneProcessor on the server
 *  - "Draw zone" button activates drawing mode on the overlay canvas
 *  - Click to add vertices; click the first vertex (or double-click) to close
 *  - Completed polygon is named then POSTed to /api/streams/{id}/zones
 *  - Saved zones appear in the sidebar list with a delete button
 *  - Zones are rendered server-side (baked into video frames); the canvas
 *    overlay is only used for the in-progress drawing interaction
 */

// zoneCanvas is declared in stream.js — reuse it
const zCtx        = zoneCanvas.getContext('2d');
const zonesToggle = document.getElementById('toggle-zones');
const btnDraw     = document.getElementById('btn-draw-zone');
const zoneList    = document.getElementById('zone-list');
const stopRadios  = document.querySelectorAll('input[name="zone-stop"]');

// ── State ─────────────────────────────────────────────────────────────────────

let drawingMode = false;
let currentPoly = [];   // [{x, y}] canvas pixels
let mousePos    = null; // {x, y} canvas pixels, live cursor
let savedZones  = [];   // [{id, name, polygon}] from server

const CLOSE_RADIUS = 14; // px — snap distance to close on first vertex

// ── Helpers ───────────────────────────────────────────────────────────────────

function zonesBase() {
  const sid = window.activeStreamId;
  return sid ? `/api/streams/${sid}/zones` : null;
}

// ── Toggle ────────────────────────────────────────────────────────────────────

zonesToggle.addEventListener('change', async () => {
  await patchConfig({ enable_zones: zonesToggle.checked });
  if (!zonesToggle.checked) cancelDrawing();
});

async function loadZoneConfig() {
  const url = window.activeStreamId
    ? `/api/streams/${window.activeStreamId}/config`
    : null;
  if (!url) return;
  try {
    const cfg = await fetch(url).then(r => r.json());
    zonesToggle.checked = cfg.enable_zones ?? false;
    const mode = cfg.zone_stop_mode ?? 'zone';
    stopRadios.forEach(r => { r.checked = (r.value === mode); });
  } catch (e) {
    console.warn('[zones] failed to load config', e);
  }
}

window.loadZoneConfig = loadZoneConfig;

// Stop mode radio buttons
stopRadios.forEach(radio => {
  radio.addEventListener('change', () => {
    patchConfig({ zone_stop_mode: radio.value });
  });
});

// Keep the header record button in sync when zone recording starts/stops
window.addEventListener('vip:event', (e) => {
  const { type, file } = e.detail;
  if (type === 'recording_started') {
    _setRecordingState(true);
  } else if (type === 'recording_stopped') {
    _setRecordingState(false);
  }
});

// ── Draw button ───────────────────────────────────────────────────────────────

btnDraw.addEventListener('click', () => {
  if (drawingMode) {
    cancelDrawing();
  } else {
    startDrawing();
  }
});

// ── Coordinate helpers ────────────────────────────────────────────────────────

function getCanvasXY(e) {
  const rect   = zoneCanvas.getBoundingClientRect();
  const scaleX = zoneCanvas.width  / rect.width;
  const scaleY = zoneCanvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top)  * scaleY,
  };
}

function normalise(x, y) {
  return [x / zoneCanvas.width, y / zoneCanvas.height];
}

function isNearFirst(x, y) {
  if (currentPoly.length === 0) return false;
  const dx = x - currentPoly[0].x;
  const dy = y - currentPoly[0].y;
  return Math.hypot(dx, dy) <= CLOSE_RADIUS;
}

// ── Drawing mode ──────────────────────────────────────────────────────────────

function startDrawing() {
  if (zoneCanvas.width === 0 || zoneCanvas.height === 0) {
    console.warn('[zones] canvas is 0×0 — stream may not have started yet');
    return;
  }
  drawingMode = true;
  currentPoly = [];
  zoneCanvas.style.cursor        = 'crosshair';
  zoneCanvas.style.pointerEvents = 'auto';
  btnDraw.textContent = 'Cancel';
  btnDraw.classList.add('btn-drawing');
}

function cancelDrawing() {
  drawingMode = false;
  currentPoly = [];
  mousePos    = null;
  zoneCanvas.style.cursor        = 'default';
  zoneCanvas.style.pointerEvents = 'none';
  btnDraw.textContent = 'Draw zone';
  btnDraw.classList.remove('btn-drawing');
  renderOverlay();
}

// ── Canvas events ─────────────────────────────────────────────────────────────

zoneCanvas.addEventListener('mousemove', (e) => {
  if (!drawingMode) return;
  mousePos = getCanvasXY(e);
  renderOverlay();
});

zoneCanvas.addEventListener('mouseleave', () => {
  mousePos = null;
  if (drawingMode) renderOverlay();
});

zoneCanvas.addEventListener('click', (e) => {
  if (!drawingMode) return;
  e.preventDefault();

  const { x, y } = getCanvasXY(e);

  if (currentPoly.length >= 3 && isNearFirst(x, y)) {
    completePoly();
    return;
  }

  currentPoly.push({ x, y });
  renderOverlay();
});

zoneCanvas.addEventListener('dblclick', (e) => {
  if (!drawingMode) return;
  e.preventDefault();
  if (currentPoly.length >= 3) {
    completePoly();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && drawingMode) cancelDrawing();
});

// ── Zone name modal (non-blocking replacement for window.prompt) ──────────────

const zoneNameOverlay  = document.getElementById('zone-name-overlay');
const zoneNameInput    = document.getElementById('zone-name-input');
const btnZoneNameOk    = document.getElementById('btn-zone-name-confirm');
const btnZoneNameCancel = document.getElementById('btn-zone-name-cancel');
const btnZoneNameClose = document.getElementById('btn-zone-name-close');

let _resolveZoneName = null;

function promptZoneName(defaultName) {
  return new Promise((resolve) => {
    _resolveZoneName = resolve;
    zoneNameInput.value = defaultName;
    zoneNameOverlay.classList.remove('hidden');
    zoneNameInput.focus();
    zoneNameInput.select();
  });
}

function _confirmZoneName() {
  const val = zoneNameInput.value.trim();
  zoneNameOverlay.classList.add('hidden');
  if (_resolveZoneName) { _resolveZoneName(val || null); _resolveZoneName = null; }
}

function _cancelZoneName() {
  zoneNameOverlay.classList.add('hidden');
  if (_resolveZoneName) { _resolveZoneName(null); _resolveZoneName = null; }
}

btnZoneNameOk.addEventListener('click', _confirmZoneName);
btnZoneNameCancel.addEventListener('click', _cancelZoneName);
btnZoneNameClose.addEventListener('click',  _cancelZoneName);
zoneNameOverlay.addEventListener('click', (e) => { if (e.target === zoneNameOverlay) _cancelZoneName(); });
zoneNameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') _confirmZoneName();
  if (e.key === 'Escape') _cancelZoneName();
});

// ── Complete polygon ──────────────────────────────────────────────────────────

async function completePoly() {
  const poly = currentPoly.slice();
  cancelDrawing();

  const base = zonesBase();
  if (!base) {
    console.warn('[zones] no active stream — cannot save zone');
    return;
  }

  const defaultName = `Zone ${savedZones.length + 1}`;
  const name = await promptZoneName(defaultName);
  if (!name) return;

  const normPoly = poly.map(({ x, y }) => normalise(x, y));

  try {
    const res = await fetch(base, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), polygon: normPoly }),
    });
    if (!res.ok) {
      const err = await res.json();
      console.error('[zones] API error:', err);
      return;
    }
    const zone = await res.json();
    savedZones.push(zone);
    renderZoneList();
  } catch (e) {
    console.error('[zones] save failed', e);
  }
}

// ── Render in-progress overlay ────────────────────────────────────────────────

function renderOverlay() {
  zCtx.clearRect(0, 0, zoneCanvas.width, zoneCanvas.height);
  if (!drawingMode || currentPoly.length === 0) return;

  const pts = currentPoly;

  zCtx.beginPath();
  zCtx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) zCtx.lineTo(pts[i].x, pts[i].y);
  if (mousePos) zCtx.lineTo(mousePos.x, mousePos.y);

  zCtx.strokeStyle = 'rgba(255, 149, 0, 0.9)';
  zCtx.lineWidth   = 2;
  zCtx.setLineDash([6, 4]);
  zCtx.stroke();
  zCtx.setLineDash([]);

  // Vertex dots
  for (let i = 0; i < pts.length; i++) {
    const snap = i === 0 && pts.length >= 3 && mousePos && isNearFirst(mousePos.x, mousePos.y);
    zCtx.beginPath();
    zCtx.arc(pts[i].x, pts[i].y, snap ? CLOSE_RADIUS : 4, 0, Math.PI * 2);
    zCtx.fillStyle   = snap ? 'rgba(255,149,0,0.35)' : '#ff9500';
    zCtx.strokeStyle = '#ff9500';
    zCtx.lineWidth   = 2;
    zCtx.fill();
    if (snap) zCtx.stroke();
  }
}

// ── Zone list sidebar ─────────────────────────────────────────────────────────

function renderZoneList() {
  zoneList.innerHTML = '';
  for (const zone of savedZones) {
    const item  = document.createElement('div');
    item.className  = 'zone-item';
    item.dataset.id = zone.id;

    const label = document.createElement('span');
    label.textContent = zone.name;

    const actions = document.createElement('div');
    actions.className = 'zone-item-actions';

    const cfg = document.createElement('button');
    cfg.className = 'zone-delete';
    cfg.title     = 'Notification settings';
    cfg.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
    cfg.addEventListener('click', () => openZoneSettings(zone));

    const del = document.createElement('button');
    del.className   = 'zone-delete';
    del.textContent = '×';
    del.title       = 'Delete zone';
    del.addEventListener('click', () => deleteZone(zone.id));

    actions.append(cfg, del);
    item.append(label, actions);
    zoneList.append(item);
  }
}

async function deleteZone(id) {
  const base = zonesBase();
  if (!base) return;
  try {
    const res = await fetch(`${base}/${id}`, { method: 'DELETE' });
    if (res.ok) {
      savedZones = savedZones.filter(z => z.id !== id);
      renderZoneList();
    } else {
      console.warn('[zones] delete failed', res.status);
    }
  } catch (e) {
    console.error('[zones] delete error', e);
  }
}

// ── Load zones on start / stream switch ───────────────────────────────────────

async function loadZones() {
  const base = zonesBase();
  if (!base) {
    savedZones = [];
    renderZoneList();
    return;
  }
  try {
    const res  = await fetch(base);
    savedZones = await res.json();
    renderZoneList();
  } catch (e) {
    console.warn('[zones] failed to load zones', e);
  }
}

// Expose globally so stream.js can call it on tab switch
window.loadZones = loadZones;

// ── Zone notification settings modal ─────────────────────────────────────────

const zsOverlay    = document.getElementById('zone-settings-overlay');
const zsZoneName   = document.getElementById('zs-zone-name');
const zsTelegram   = document.getElementById('zs-telegram-msg');
const zsEmail      = document.getElementById('zs-email-msg');
const btnZsSave    = document.getElementById('btn-zone-settings-save');
const btnZsCancel  = document.getElementById('btn-zone-settings-cancel');
const btnZsClose   = document.getElementById('btn-zone-settings-close');

let _zsCurrentZone = null;

function closeZoneSettings() {
  zsOverlay.classList.add('hidden');
  _zsCurrentZone = null;
}

async function openZoneSettings(zone) {
  _zsCurrentZone = zone;
  zsZoneName.textContent = zone.name;
  zsTelegram.value = '';
  zsEmail.value    = '';

  const base = zonesBase();
  if (base) {
    try {
      const res  = await fetch(`${base}/${zone.id}/settings`);
      const data = await res.json();
      zsTelegram.value = data.telegram_message ?? '';
      zsEmail.value    = data.email_message    ?? '';
    } catch (e) {
      console.warn('[zones] failed to load zone settings', e);
    }
  }

  zsOverlay.classList.remove('hidden');
  zsTelegram.focus();
}

btnZsSave.addEventListener('click', async () => {
  if (!_zsCurrentZone) return;
  const base = zonesBase();
  if (!base) return;
  try {
    await fetch(`${base}/${_zsCurrentZone.id}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        telegram_message: zsTelegram.value.trim(),
        email_message:    zsEmail.value.trim(),
      }),
    });
  } catch (e) {
    console.error('[zones] failed to save zone settings', e);
  }
  closeZoneSettings();
});

btnZsCancel.addEventListener('click', closeZoneSettings);
btnZsClose.addEventListener('click',  closeZoneSettings);
zsOverlay.addEventListener('click', (e) => { if (e.target === zsOverlay) closeZoneSettings(); });

// ─────────────────────────────────────────────────────────────────────────────

// Zone canvas is transparent and non-interactive by default
zoneCanvas.style.pointerEvents = 'none';
zoneCanvas.style.cursor        = 'default';

// loadZones() is called by stream.js after activeStreamId is set
