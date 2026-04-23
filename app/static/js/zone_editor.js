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
  await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enable_zones: zonesToggle.checked }),
  });
  if (!zonesToggle.checked) cancelDrawing();
});

fetch('/api/config')
  .then(r => r.json())
  .then(cfg => {
    zonesToggle.checked = cfg.enable_zones ?? false;
    const mode = cfg.zone_stop_mode ?? 'zone';
    stopRadios.forEach(r => { r.checked = (r.value === mode); });
  })
  .catch(e => console.warn('[zones] failed to load config', e));

// Stop mode radio buttons
stopRadios.forEach(radio => {
  radio.addEventListener('change', () => {
    fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zone_stop_mode: radio.value }),
    });
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
  const name = window.prompt('Zone name:', defaultName);
  if (!name || !name.trim()) return;

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

    const del = document.createElement('button');
    del.className   = 'zone-delete';
    del.textContent = '×';
    del.title       = 'Delete zone';
    del.addEventListener('click', () => deleteZone(zone.id));

    item.append(label, del);
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

// Zone canvas is transparent and non-interactive by default
zoneCanvas.style.pointerEvents = 'none';
zoneCanvas.style.cursor        = 'default';

loadZones();
