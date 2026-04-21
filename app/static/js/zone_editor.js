/**
 * zone_editor.js — Detection zone drawing and management
 *
 * NOTE: zoneCanvas is already declared by stream.js — do NOT re-declare it here.
 *
 * UX:
 *  - Toggle switch enables/disables the ZoneProcessor on the server
 *  - "Draw zone" button activates drawing mode on the overlay canvas
 *  - Click to add vertices; click the first vertex (or double-click) to close
 *  - Completed polygon is named then POSTed to /api/zones
 *  - Saved zones appear in the sidebar list with a delete button
 *  - Zones are rendered server-side (baked into video frames); the canvas
 *    overlay is only used for the in-progress drawing interaction
 */

// zoneCanvas is declared in stream.js — reuse it
const zCtx        = zoneCanvas.getContext('2d');
const zonesToggle = document.getElementById('toggle-zones');
const btnDraw     = document.getElementById('btn-draw-zone');
const zoneList    = document.getElementById('zone-list');

// ── State ─────────────────────────────────────────────────────────────────────

let drawingMode = false;
let currentPoly = [];   // [{x, y}] canvas pixels
let mousePos    = null; // {x, y} canvas pixels, live cursor
let savedZones  = [];   // [{id, name, polygon}] from server

const CLOSE_RADIUS = 14; // px — snap distance to close on first vertex

// ── Toggle ────────────────────────────────────────────────────────────────────

zonesToggle.addEventListener('change', async () => {
  console.log('[zones] toggle →', zonesToggle.checked);
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
    console.log('[zones] initial state: enable_zones =', zonesToggle.checked);
  })
  .catch(e => console.warn('[zones] failed to load config', e));

// ── Draw button ───────────────────────────────────────────────────────────────

btnDraw.addEventListener('click', () => {
  if (drawingMode) {
    console.log('[zones] drawing cancelled');
    cancelDrawing();
  } else {
    startDrawing();
  }
});

// ── Coordinate helpers ────────────────────────────────────────────────────────

function getCanvasXY(e) {
  const rect   = zoneCanvas.getBoundingClientRect();
  // Account for CSS scaling (canvas logical size vs displayed size)
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
  console.log('[zones] drawing mode ON — canvas size:', zoneCanvas.width, '×', zoneCanvas.height);
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

  // Close polygon when clicking near the first vertex (need ≥3 pts already)
  if (currentPoly.length >= 3 && isNearFirst(x, y)) {
    console.log('[zones] closing polygon by snapping to first vertex');
    completePoly();
    return;
  }

  currentPoly.push({ x, y });
  const [nx, ny] = normalise(x, y);
  console.log(`[zones] vertex #${currentPoly.length} added — canvas:(${Math.round(x)}, ${Math.round(y)}) norm:(${nx.toFixed(3)}, ${ny.toFixed(3)})`);
  renderOverlay();
});

zoneCanvas.addEventListener('dblclick', (e) => {
  if (!drawingMode) return;
  e.preventDefault();
  if (currentPoly.length >= 3) {
    console.log('[zones] closing polygon via double-click');
    completePoly();
  } else {
    console.warn('[zones] double-click ignored — need at least 3 vertices (have', currentPoly.length, ')');
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && drawingMode) {
    console.log('[zones] drawing cancelled via Escape');
    cancelDrawing();
  }
});

// ── Complete polygon ──────────────────────────────────────────────────────────

async function completePoly() {
  const poly = currentPoly.slice();
  cancelDrawing();

  const defaultName = `Zone ${savedZones.length + 1}`;
  const name = window.prompt('Zone name:', defaultName);
  if (!name || !name.trim()) {
    console.log('[zones] zone creation cancelled (no name given)');
    return;
  }

  const normPoly = poly.map(({ x, y }) => normalise(x, y));
  console.log('[zones] saving zone "%s" with %d vertices:', name.trim(), normPoly.length, normPoly);

  try {
    const res = await fetch('/api/zones', {
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
    console.log('[zones] zone created:', zone);
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
  console.log('[zones] sidebar rendered:', savedZones.length, 'zone(s)');
}

async function deleteZone(id) {
  console.log('[zones] deleting zone', id);
  try {
    const res = await fetch(`/api/zones/${id}`, { method: 'DELETE' });
    if (res.ok) {
      savedZones = savedZones.filter(z => z.id !== id);
      renderZoneList();
      console.log('[zones] zone deleted');
    } else {
      console.warn('[zones] delete failed', res.status);
    }
  } catch (e) {
    console.error('[zones] delete error', e);
  }
}

// ── Load zones on start ───────────────────────────────────────────────────────

async function loadZones() {
  try {
    const res  = await fetch('/api/zones');
    savedZones = await res.json();
    console.log('[zones] loaded', savedZones.length, 'zone(s) from server');
    renderZoneList();
  } catch (e) {
    console.warn('[zones] failed to load zones', e);
  }
}

// Zone canvas is transparent and non-interactive by default
zoneCanvas.style.pointerEvents = 'none';
zoneCanvas.style.cursor        = 'default';

console.log('[zones] zone_editor.js loaded ✓');
loadZones();
