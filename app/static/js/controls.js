/**
 * controls.js — sidebar panel interactions
 *
 * Responsible for:
 *  - Collapsible feature sections (click header to expand/collapse)
 *  - Toggle switches wired to PUT /api/config
 *  - Range sliders with debounced PUT /api/config
 *  - Populating slider values from GET /api/config on load
 */

const DEBOUNCE_MS = 400;

// ── Helpers ───────────────────────────────────────────────────────────────────

async function patchConfig(body) {
  try {
    await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {
    console.warn('config update failed', e);
  }
  // Always resolves so callers can chain .then()
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ── Collapsible sections ──────────────────────────────────────────────────────

document.querySelectorAll('.feature-header').forEach((header) => {
  header.addEventListener('click', (e) => {
    // Don't collapse when clicking the toggle switch itself
    if (e.target.closest('.toggle-switch')) return;

    const body = header.nextElementSibling;
    body.classList.toggle('collapsed');
  });
});

// ── Motion Tracking ───────────────────────────────────────────────────────────

const motionToggle      = document.getElementById('toggle-motion');
const sensitivitySlider = document.getElementById('motion-sensitivity');
const sensitivityVal    = document.getElementById('motion-sensitivity-val');
const minAreaSlider     = document.getElementById('motion-min-area');
const minAreaVal        = document.getElementById('motion-min-area-val');
const trailSlider       = document.getElementById('motion-trail');
const trailVal          = document.getElementById('motion-trail-val');
const motionBody        = document.getElementById('motion-body');

// Toggle switch
motionToggle.addEventListener('change', () => {
  patchConfig({ enable_motion: motionToggle.checked });
  // Dim sliders when disabled
  const sliders = motionBody.querySelectorAll('input[type="range"]');
  sliders.forEach(s => s.disabled = !motionToggle.checked);
});

// Sliders — update display immediately, debounce the API call
sensitivitySlider.addEventListener('input', () => {
  sensitivityVal.textContent = sensitivitySlider.value;
});
sensitivitySlider.addEventListener('input', debounce(() => {
  patchConfig({ motion_mog2_threshold: parseInt(sensitivitySlider.value) });
}, DEBOUNCE_MS));

minAreaSlider.addEventListener('input', () => {
  minAreaVal.textContent = minAreaSlider.value;
});
minAreaSlider.addEventListener('input', debounce(() => {
  patchConfig({ motion_min_area: parseInt(minAreaSlider.value) });
}, DEBOUNCE_MS));

trailSlider.addEventListener('input', () => {
  trailVal.textContent = trailSlider.value;
});
trailSlider.addEventListener('input', debounce(() => {
  patchConfig({ motion_trail_length: parseInt(trailSlider.value) });
}, DEBOUNCE_MS));

// ── Populate UI from server config on load ────────────────────────────────────

async function loadConfig() {
  try {
    const res  = await fetch('/api/config');
    const data = await res.json();

    // Motion toggle + body collapse state
    motionToggle.checked = data.enable_motion;
    if (!data.enable_motion) {
      motionBody.querySelectorAll('input[type="range"]').forEach(s => s.disabled = true);
    }

    // Sliders
    sensitivitySlider.value = data.motion_mog2_threshold;
    sensitivityVal.textContent  = data.motion_mog2_threshold;

    minAreaSlider.value = data.motion_min_area;
    minAreaVal.textContent  = data.motion_min_area;

    trailSlider.value = data.motion_trail_length;
    trailVal.textContent  = data.motion_trail_length;

  } catch (e) {
    console.warn('failed to load config', e);
  }
}

loadConfig();


// ── Visual Settings Modal ─────────────────────────────────────────────────────

const VISUAL_DEFAULTS = {
  motion_trail_color:       '#32dc64',
  motion_trail_max_radius:  5,
  motion_contour_color:     '#32dc64',
  motion_contour_thickness: 2,
  motion_arrow_color:       '#00c8ff',
  motion_arrow_thickness:   2,
  motion_arrow_enabled:     true,
  motion_center_color:      '#ffffff',
  motion_center_radius:     5,
  motion_center_enabled:    true,
};

const overlay   = document.getElementById('modal-overlay');
const btnOpen   = document.getElementById('btn-visual-settings');
const btnClose  = document.getElementById('btn-modal-close');
const btnApply  = document.getElementById('btn-modal-apply');
const btnReset  = document.getElementById('btn-modal-reset');

// Helper: read a range input and update its sibling value label
function bindRange(id, valId) {
  const input = document.getElementById(id);
  const label = document.getElementById(valId);
  input.addEventListener('input', () => { label.textContent = input.value; });
  return input;
}

const vsTrailColor        = document.getElementById('vs-trail-color');
const vsTrailRadius       = bindRange('vs-trail-radius',       'vs-trail-radius-val');
const vsContourColor      = document.getElementById('vs-contour-color');
const vsContourThickness  = bindRange('vs-contour-thickness',  'vs-contour-thickness-val');
const vsArrowEnabled      = document.getElementById('vs-arrow-enabled');
const vsArrowColor        = document.getElementById('vs-arrow-color');
const vsArrowThickness    = bindRange('vs-arrow-thickness',    'vs-arrow-thickness-val');
const vsCenterEnabled     = document.getElementById('vs-center-enabled');
const vsCenterColor       = document.getElementById('vs-center-color');
const vsCenterRadius      = bindRange('vs-center-radius',      'vs-center-radius-val');

function populateModal(cfg) {
  vsTrailColor.value       = cfg.motion_trail_color       ?? VISUAL_DEFAULTS.motion_trail_color;
  vsTrailRadius.value      = cfg.motion_trail_max_radius  ?? VISUAL_DEFAULTS.motion_trail_max_radius;
  document.getElementById('vs-trail-radius-val').textContent = vsTrailRadius.value;

  vsContourColor.value     = cfg.motion_contour_color      ?? VISUAL_DEFAULTS.motion_contour_color;
  vsContourThickness.value = cfg.motion_contour_thickness  ?? VISUAL_DEFAULTS.motion_contour_thickness;
  document.getElementById('vs-contour-thickness-val').textContent = vsContourThickness.value;

  vsArrowEnabled.checked   = cfg.motion_arrow_enabled      ?? VISUAL_DEFAULTS.motion_arrow_enabled;
  vsArrowColor.value       = cfg.motion_arrow_color        ?? VISUAL_DEFAULTS.motion_arrow_color;
  vsArrowThickness.value   = cfg.motion_arrow_thickness    ?? VISUAL_DEFAULTS.motion_arrow_thickness;
  document.getElementById('vs-arrow-thickness-val').textContent = vsArrowThickness.value;

  vsCenterEnabled.checked  = cfg.motion_center_enabled     ?? VISUAL_DEFAULTS.motion_center_enabled;
  vsCenterColor.value      = cfg.motion_center_color       ?? VISUAL_DEFAULTS.motion_center_color;
  vsCenterRadius.value     = cfg.motion_center_radius      ?? VISUAL_DEFAULTS.motion_center_radius;
  document.getElementById('vs-center-radius-val').textContent = vsCenterRadius.value;
}

function openModal() {
  fetch('/api/config')
    .then(r => r.json())
    .then(cfg => {
      populateModal(cfg);
      overlay.classList.remove('hidden');
    });
}

function closeModal() {
  overlay.classList.add('hidden');
}

btnOpen.addEventListener('click', openModal);
btnClose.addEventListener('click', closeModal);
overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

btnApply.addEventListener('click', () => {
  patchConfig({
    motion_trail_color:       vsTrailColor.value,
    motion_trail_max_radius:  parseInt(vsTrailRadius.value),
    motion_contour_color:     vsContourColor.value,
    motion_contour_thickness: parseInt(vsContourThickness.value),
    motion_arrow_enabled:     vsArrowEnabled.checked,
    motion_arrow_color:       vsArrowColor.value,
    motion_arrow_thickness:   parseInt(vsArrowThickness.value),
    motion_center_enabled:    vsCenterEnabled.checked,
    motion_center_color:      vsCenterColor.value,
    motion_center_radius:     parseInt(vsCenterRadius.value),
  }).then(closeModal);
});

btnReset.addEventListener('click', () => {
  populateModal(VISUAL_DEFAULTS);
});
