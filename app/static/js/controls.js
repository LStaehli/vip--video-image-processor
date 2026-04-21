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
const dilateSlider      = document.getElementById('motion-dilate');
const dilateVal         = document.getElementById('motion-dilate-val');
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

dilateSlider.addEventListener('input', () => {
  dilateVal.textContent = dilateSlider.value;
});
dilateSlider.addEventListener('input', debounce(() => {
  patchConfig({ motion_dilate_kernel: parseInt(dilateSlider.value) });
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

    dilateSlider.value = data.motion_dilate_kernel;
    dilateVal.textContent  = data.motion_dilate_kernel;

  } catch (e) {
    console.warn('failed to load config', e);
  }
}

loadConfig();


// ── Visual Settings Modal ─────────────────────────────────────────────────────

const VISUAL_DEFAULTS = {
  motion_trail_enabled:     true,
  motion_trail_color:       '#32dc64',
  motion_trail_length:      20,
  motion_trail_max_radius:  5,
  motion_contour_enabled:   true,
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

const vsTrailEnabled      = document.getElementById('vs-trail-enabled');
const vsTrailColor        = document.getElementById('vs-trail-color');
const vsTrailLength       = bindRange('vs-trail-length',       'vs-trail-length-val');
const vsTrailRadius       = bindRange('vs-trail-radius',       'vs-trail-radius-val');
const vsContourEnabled    = document.getElementById('vs-contour-enabled');
const vsContourColor      = document.getElementById('vs-contour-color');
const vsContourThickness  = bindRange('vs-contour-thickness',  'vs-contour-thickness-val');
const vsArrowEnabled      = document.getElementById('vs-arrow-enabled');
const vsArrowColor        = document.getElementById('vs-arrow-color');
const vsArrowThickness    = bindRange('vs-arrow-thickness',    'vs-arrow-thickness-val');
const vsCenterEnabled     = document.getElementById('vs-center-enabled');
const vsCenterColor       = document.getElementById('vs-center-color');
const vsCenterRadius      = bindRange('vs-center-radius',      'vs-center-radius-val');

function populateModal(cfg) {
  vsTrailEnabled.checked   = cfg.motion_trail_enabled     ?? VISUAL_DEFAULTS.motion_trail_enabled;
  vsTrailColor.value       = cfg.motion_trail_color       ?? VISUAL_DEFAULTS.motion_trail_color;
  vsTrailLength.value      = cfg.motion_trail_length      ?? VISUAL_DEFAULTS.motion_trail_length;
  document.getElementById('vs-trail-length-val').textContent = vsTrailLength.value;
  vsTrailRadius.value      = cfg.motion_trail_max_radius  ?? VISUAL_DEFAULTS.motion_trail_max_radius;
  document.getElementById('vs-trail-radius-val').textContent = vsTrailRadius.value;

  vsContourEnabled.checked = cfg.motion_contour_enabled    ?? VISUAL_DEFAULTS.motion_contour_enabled;
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
    motion_trail_enabled:     vsTrailEnabled.checked,
    motion_trail_color:       vsTrailColor.value,
    motion_trail_length:      parseInt(vsTrailLength.value),
    motion_trail_max_radius:  parseInt(vsTrailRadius.value),
    motion_contour_enabled:   vsContourEnabled.checked,
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


// ── Stream Settings Modal ─────────────────────────────────────────────────────

const streamOverlay       = document.getElementById('stream-settings-overlay');
const btnStreamSettings   = document.getElementById('btn-stream-settings');
const btnStreamClose      = document.getElementById('btn-stream-settings-close');
const btnStreamCancel     = document.getElementById('btn-stream-settings-cancel');
const btnStreamApply      = document.getElementById('btn-stream-settings-apply');

const ssSource    = document.getElementById('ss-source');
const ssFps       = bindRange('ss-fps',     'ss-fps-val');
const ssQuality   = bindRange('ss-quality', 'ss-quality-val');

async function openStreamSettings() {
  // Fetch both status (live stats) and config (editable values) in parallel
  const [statusRes, configRes] = await Promise.all([
    fetch('/api/status'),
    fetch('/api/config'),
  ]);
  const status = await statusRes.json();
  const config = await configRes.json();

  // Populate editable source
  ssSource.value = config.stream_url ?? status.source ?? '';

  // Populate read-only stats
  document.getElementById('ss-connected').textContent  = status.stream_connected ? 'Connected' : 'Disconnected';
  document.getElementById('ss-actual-fps').textContent = `${status.actual_fps} fps`;
  document.getElementById('ss-clients').textContent    = status.video_clients;

  // Populate editable pipeline fields
  ssFps.value     = config.target_fps;
  document.getElementById('ss-fps-val').textContent     = config.target_fps;
  ssQuality.value = config.jpeg_quality;
  document.getElementById('ss-quality-val').textContent = config.jpeg_quality;

  streamOverlay.classList.remove('hidden');
}

function closeStreamSettings() {
  streamOverlay.classList.add('hidden');
}

btnStreamSettings.addEventListener('click', openStreamSettings);
btnStreamClose.addEventListener('click',  closeStreamSettings);
btnStreamCancel.addEventListener('click', closeStreamSettings);
streamOverlay.addEventListener('click', (e) => { if (e.target === streamOverlay) closeStreamSettings(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !streamOverlay.classList.contains('hidden')) closeStreamSettings();
});

btnStreamApply.addEventListener('click', async () => {
  await patchConfig({
    stream_url:   ssSource.value.trim(),
    target_fps:   parseInt(ssFps.value),
    jpeg_quality: parseInt(ssQuality.value),
  });
  closeStreamSettings();
});


// ── General Settings Modal ────────────────────────────────────────────────────

const generalOverlay    = document.getElementById('general-settings-overlay');
const btnGeneralOpen    = document.getElementById('btn-general-settings');
const btnGeneralClose   = document.getElementById('btn-general-settings-close');
const btnGeneralCancel  = document.getElementById('btn-general-settings-cancel');
const btnGeneralApply   = document.getElementById('btn-general-settings-apply');

const gsOutputDir       = document.getElementById('gs-output-dir');
const gsProjectName     = document.getElementById('gs-project-name');
const gsFilenamePattern = document.getElementById('gs-filename-pattern');

async function openGeneralSettings() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    gsOutputDir.value       = cfg.recording_output_dir       ?? '';
    gsProjectName.value     = cfg.recording_project_name     ?? '';
    gsFilenamePattern.value = cfg.recording_filename_pattern ?? '';
  } catch (e) {
    console.warn('failed to load general settings', e);
  }
  generalOverlay.classList.remove('hidden');
}

function closeGeneralSettings() {
  generalOverlay.classList.add('hidden');
}

btnGeneralOpen.addEventListener('click', openGeneralSettings);
btnGeneralClose.addEventListener('click', closeGeneralSettings);
btnGeneralCancel.addEventListener('click', closeGeneralSettings);
generalOverlay.addEventListener('click', (e) => { if (e.target === generalOverlay) closeGeneralSettings(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !generalOverlay.classList.contains('hidden')) closeGeneralSettings();
});

btnGeneralApply.addEventListener('click', async () => {
  await patchConfig({
    recording_output_dir:       gsOutputDir.value.trim(),
    recording_project_name:     gsProjectName.value.trim(),
    recording_filename_pattern: gsFilenamePattern.value.trim(),
  });
  closeGeneralSettings();
});


// ── Record Button ─────────────────────────────────────────────────────────────

const btnRecord   = document.getElementById('btn-record');
const recordTimer = document.getElementById('record-timer');

let _recordingActive  = false;
let _recordingStart   = null;
let _recordingTimerId = null;

function _formatElapsed(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function _startTimerDisplay() {
  _recordingStart = Date.now();
  recordTimer.textContent = '00:00';
  recordTimer.classList.add('visible');
  _recordingTimerId = setInterval(() => {
    const elapsed = Math.floor((Date.now() - _recordingStart) / 1000);
    recordTimer.textContent = _formatElapsed(elapsed);
  }, 1000);
}

function _stopTimerDisplay() {
  clearInterval(_recordingTimerId);
  _recordingTimerId = null;
  recordTimer.textContent = '';
  recordTimer.classList.remove('visible');
}

function _setRecordingState(active) {
  _recordingActive = active;
  if (active) {
    btnRecord.classList.add('recording');
    btnRecord.title = 'Stop recording';
    btnRecord.setAttribute('aria-label', 'Stop recording');
    _startTimerDisplay();
  } else {
    btnRecord.classList.remove('recording');
    btnRecord.title = 'Start recording';
    btnRecord.setAttribute('aria-label', 'Start / stop recording');
    _stopTimerDisplay();
  }
}

btnRecord.addEventListener('click', async () => {
  if (_recordingActive) {
    // Stop
    try {
      const res  = await fetch('/api/recording/stop', { method: 'POST' });
      const data = await res.json();
      console.info('Recording saved to', data.saved_to);
    } catch (e) {
      console.warn('Failed to stop recording', e);
    }
    _setRecordingState(false);
  } else {
    // Start
    try {
      const res = await fetch('/api/recording/start', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        console.warn('Failed to start recording', err);
        return;
      }
    } catch (e) {
      console.warn('Failed to start recording', e);
      return;
    }
    _setRecordingState(true);
  }
});

// ── Screenshot Button ─────────────────────────────────────────────────────────

const btnScreenshot = document.getElementById('btn-screenshot');

btnScreenshot.addEventListener('click', async () => {
  try {
    const res = await fetch('/api/recording/screenshot', { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      console.warn('Screenshot failed', err);
      return;
    }
    const data = await res.json();
    console.info('Screenshot saved to', data.saved_to);
  } catch (e) {
    console.warn('Screenshot request failed', e);
    return;
  }
  // Brief green flash on success
  btnScreenshot.classList.add('flash');
  btnScreenshot.addEventListener('animationend', () => btnScreenshot.classList.remove('flash'), { once: true });
});


// Sync recording state on page load (in case server was already recording)
fetch('/api/recording/status')
  .then(r => r.json())
  .then(data => {
    if (data.is_recording) {
      _recordingActive = true;
      btnRecord.classList.add('recording');
      btnRecord.title = 'Stop recording';
      btnRecord.setAttribute('aria-label', 'Stop recording');
      // Approximate timer from elapsed_seconds
      _recordingStart = Date.now() - (data.elapsed_seconds ?? 0) * 1000;
      recordTimer.textContent = _formatElapsed(Math.floor(data.elapsed_seconds ?? 0));
      recordTimer.classList.add('visible');
      _recordingTimerId = setInterval(() => {
        const elapsed = Math.floor((Date.now() - _recordingStart) / 1000);
        recordTimer.textContent = _formatElapsed(elapsed);
      }, 1000);
    }
  })
  .catch(() => {});
