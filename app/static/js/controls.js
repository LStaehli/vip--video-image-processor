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

// ── Sidebar toggle ────────────────────────────────────────────────────────────

(function () {
  const sidebar  = document.getElementById('controls');
  const btn      = document.getElementById('btn-toggle-sidebar');
  const iconLine = document.getElementById('sidebar-icon').querySelector('line');

  function setSidebar(collapsed) {
    sidebar.classList.toggle('collapsed', collapsed);
    // Flip the vertical divider line to hint open/close direction
    iconLine.setAttribute('x1', collapsed ? '9' : '15');
    iconLine.setAttribute('x2', collapsed ? '9' : '15');
    localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0');
  }

  btn.addEventListener('click', () => setSidebar(!sidebar.classList.contains('collapsed')));

  // Restore state across page loads
  setSidebar(localStorage.getItem('sidebarCollapsed') === '1');
})();

// ── Helpers ───────────────────────────────────────────────────────────────────

function _streamConfigUrl() {
  return window.activeStreamId ? `/api/streams/${window.activeStreamId}/config` : null;
}

// Per-stream feature config (motion, detection, zones, faces, fps, quality)
async function patchConfig(body) {
  const url = _streamConfigUrl();
  if (!url) { console.warn('[config] no active stream'); return; }
  try {
    await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {
    console.warn('config update failed', e);
  }
}

// Global-only config (recording paths) — still hits /api/config
async function patchGlobalConfig(body) {
  try {
    await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {
    console.warn('global config update failed', e);
  }
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

// ── Detection Zones ───────────────────────────────────────────────────────────

const zoneNotifToggle = document.getElementById('toggle-zone-notif');

zoneNotifToggle?.addEventListener('change', () => {
  patchConfig({ notify_on_zone_trigger: zoneNotifToggle.checked });
});

// ── Object Detection ──────────────────────────────────────────────────────────

const detToggle      = document.getElementById('toggle-detection');
const detModel       = document.getElementById('det-model');
const detConfidence  = document.getElementById('det-confidence');
const detConfidenceVal = document.getElementById('det-confidence-val');
const detSkip        = document.getElementById('det-skip');
const detSkipVal     = document.getElementById('det-skip-val');
const detClasses     = document.getElementById('det-classes');

detToggle.addEventListener('change', () => {
  patchConfig({ enable_detection: detToggle.checked });
});

detModel.addEventListener('change', () => {
  patchConfig({ yolo_model: detModel.value });
});

detConfidence.addEventListener('input', () => {
  detConfidenceVal.textContent = `${detConfidence.value}%`;
});
detConfidence.addEventListener('input', debounce(() => {
  patchConfig({ yolo_confidence: parseInt(detConfidence.value) / 100 });
}, DEBOUNCE_MS));

detSkip.addEventListener('input', () => {
  detSkipVal.textContent = `${detSkip.value}f`;
});
detSkip.addEventListener('input', debounce(() => {
  patchConfig({ yolo_skip_frames: parseInt(detSkip.value) });
}, DEBOUNCE_MS));

detClasses.addEventListener('change', debounce(() => {
  patchConfig({ detect_classes: detClasses.value.trim() });
}, DEBOUNCE_MS));

// ── Model loading indicator ───────────────────────────────────────────────────

const detLoading      = document.getElementById('det-loading');
const detLoadingLabel = document.getElementById('det-loading-label');
const detSection      = document.getElementById('section-detection');

window.addEventListener('vip:event', (e) => {
  const { type, model } = e.detail ?? {};
  if (type === 'model_loading') {
    detLoadingLabel.textContent = `Loading ${model ?? 'model'}…`;
    detLoading.classList.remove('hidden');
    // Expand the panel so the indicator is visible
    const body = detSection.querySelector('.feature-body');
    if (body) body.classList.remove('collapsed');
  } else if (type === 'model_ready' || type === 'model_error') {
    detLoading.classList.add('hidden');
    if (type === 'model_error') {
      detLoadingLabel.textContent = 'Load failed';
    }
  }
});

// ── Face Recognition ──────────────────────────────────────────────────────────

const faceToggle         = document.getElementById('toggle-faces');
const faceNotifToggle    = document.getElementById('toggle-face-notif');
const faceList           = document.getElementById('face-list');
const btnEnrollFace      = document.getElementById('btn-enroll-face');

// Face config modal elements (inside #face-config-overlay)
const faceModel          = document.getElementById('face-model');
const faceSimilarity     = bindRange('face-similarity', 'face-similarity-val');
const faceSkip           = bindRange('face-skip',       'face-skip-val');
const faceLandmarks      = document.getElementById('face-landmarks');
const faceAutoEnroll     = document.getElementById('face-auto-enroll');
const faceAutoScore      = bindRange('face-auto-score', 'face-auto-score-val');
const faceAutoScoreField = document.getElementById('face-auto-enroll-quality-field');

faceToggle.addEventListener('change', () => {
  patchConfig({ enable_faces: faceToggle.checked });
});

faceNotifToggle?.addEventListener('change', () => {
  patchConfig({ notify_on_face_recognized: faceNotifToggle.checked });
});

// Show/hide quality threshold when auto-enroll is toggled inside the modal
faceAutoEnroll.addEventListener('change', () => {
  faceAutoScoreField.style.display = faceAutoEnroll.checked ? '' : 'none';
});

// ── Face Config Modal ─────────────────────────────────────────────────────────

const faceConfigOverlay   = document.getElementById('face-config-overlay');
const btnFaceConfig       = document.getElementById('btn-face-config');
const btnFaceConfigClose  = document.getElementById('btn-face-config-close');
const btnFaceConfigCancel = document.getElementById('btn-face-config-cancel');
const btnFaceConfigApply  = document.getElementById('btn-face-config-apply');

async function openFaceConfig() {
  const url = _streamConfigUrl();
  if (!url) return;
  try {
    const res  = await fetch(url);
    const data = await res.json();
    if (data.face_model)                  faceModel.value    = data.face_model;
    if (data.face_similarity_threshold !== undefined) {
      faceSimilarity.value = Math.round(data.face_similarity_threshold * 100);
      document.getElementById('face-similarity-val').textContent = `${faceSimilarity.value}%`;
    }
    if (data.face_skip_frames !== undefined) {
      faceSkip.value = data.face_skip_frames;
      document.getElementById('face-skip-val').textContent = `${faceSkip.value}f`;
    }
    if (data.face_show_landmarks !== undefined)  faceLandmarks.checked  = data.face_show_landmarks;
    if (data.face_auto_enroll    !== undefined) {
      faceAutoEnroll.checked = data.face_auto_enroll;
      faceAutoScoreField.style.display = data.face_auto_enroll ? '' : 'none';
    }
    if (data.face_auto_enroll_min_score !== undefined) {
      faceAutoScore.value = Math.round(data.face_auto_enroll_min_score * 100);
      document.getElementById('face-auto-score-val').textContent = `${faceAutoScore.value}%`;
    }
  } catch (e) {
    console.warn('[face-config] failed to load config', e);
  }
  faceConfigOverlay.classList.remove('hidden');
}

function closeFaceConfig() {
  faceConfigOverlay.classList.add('hidden');
}

btnFaceConfig.addEventListener('click', openFaceConfig);
btnFaceConfigClose.addEventListener('click', closeFaceConfig);
btnFaceConfigCancel.addEventListener('click', closeFaceConfig);
faceConfigOverlay.addEventListener('click', (e) => { if (e.target === faceConfigOverlay) closeFaceConfig(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !faceConfigOverlay.classList.contains('hidden')) closeFaceConfig();
});

btnFaceConfigApply.addEventListener('click', async () => {
  await patchConfig({
    face_model:                   faceModel.value,
    face_similarity_threshold:    parseInt(faceSimilarity.value) / 100,
    face_skip_frames:             parseInt(faceSkip.value),
    face_show_landmarks:          faceLandmarks.checked,
    face_auto_enroll:             faceAutoEnroll.checked,
    face_auto_enroll_min_score:   parseInt(faceAutoScore.value) / 100,
  });
  closeFaceConfig();
});

// ── Face Profiles Modal ───────────────────────────────────────────────────────

const faceProfilesOverlay  = document.getElementById('face-profiles-overlay');
const btnFaceProfiles      = document.getElementById('btn-face-profiles');
const btnFaceProfilesClose = document.getElementById('btn-face-profiles-close');
const btnFaceProfilesDone  = document.getElementById('btn-face-profiles-done');

async function openFaceProfiles() {
  await loadFaceList();
  faceProfilesOverlay.classList.remove('hidden');
}

function closeFaceProfiles() {
  faceProfilesOverlay.classList.add('hidden');
}

btnFaceProfiles.addEventListener('click', openFaceProfiles);
btnFaceProfilesClose.addEventListener('click', closeFaceProfiles);
btnFaceProfilesDone.addEventListener('click',  closeFaceProfiles);
faceProfilesOverlay.addEventListener('click', (e) => { if (e.target === faceProfilesOverlay) closeFaceProfiles(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !faceProfilesOverlay.classList.contains('hidden')) closeFaceProfiles();
});

async function loadFaceList() {
  try {
    const [facesRes, settingsRes] = await Promise.all([
      fetch('/api/faces'),
      fetch('/api/faces/settings'),
    ]);
    const { faces = [] }  = await facesRes.json();
    const allSettings     = await settingsRes.json();
    renderFaceList(faces, allSettings);
  } catch (e) {
    console.warn('Failed to load face list', e);
  }
}

const _BELL_ON_SVG  = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`;
const _BELL_OFF_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

function renderFaceList(faces, allSettings = {}) {
  faceList.innerHTML = '';
  if (faces.length === 0) {
    faceList.innerHTML = '<p class="field-hint" style="margin-top:0.5rem">No faces enrolled yet.</p>';
    return;
  }
  faces.forEach(({ name, created_at }) => {
    const notifSettings  = allSettings[name] ?? {};
    const notifyEnabled  = notifSettings.notify_enabled !== false; // default true
    const item = document.createElement('div');
    item.className = 'face-item';

    const date = created_at
      ? new Date(created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
      : '';

    item.innerHTML = `
      <div class="face-item-info">
        <span class="face-item-name">${name}</span>
        <span class="face-item-meta">${date}</span>
      </div>
      <div class="face-item-actions">
        <button class="face-item-btn face-bell-btn ${notifyEnabled ? 'active' : ''}" title="${notifyEnabled ? 'Notifications on — click to disable' : 'Notifications off — click to enable'}">${notifyEnabled ? _BELL_ON_SVG : _BELL_OFF_SVG}</button>
        <button class="face-item-btn face-notif-btn" title="Notification settings"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></button>
        <button class="face-item-btn face-rename-btn" title="Rename">&#9998;</button>
        <button class="face-item-btn zone-delete" title="Remove">&times;</button>
      </div>`;

    // Bell: instant toggle of notify_enabled without opening modal
    item.querySelector('.face-bell-btn').addEventListener('click', async (e) => {
      const btn     = e.currentTarget;
      const isOn    = btn.classList.contains('active');
      const newVal  = !isOn;
      btn.classList.toggle('active', newVal);
      btn.innerHTML = newVal ? _BELL_ON_SVG : _BELL_OFF_SVG;
      btn.title     = newVal ? 'Notifications on — click to disable' : 'Notifications off — click to enable';
      // Preserve existing message templates while toggling
      const cur = await fetch(`/api/faces/${encodeURIComponent(name)}/settings`).then(r => r.json()).catch(() => ({}));
      await fetch(`/api/faces/${encodeURIComponent(name)}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notify_enabled:   newVal,
          telegram_message: cur.telegram_message ?? '',
          email_message:    cur.email_message    ?? '',
        }),
      });
    });

    item.querySelector('.face-notif-btn').addEventListener('click', () => openFaceSettings(name));

    item.querySelector('.face-rename-btn').addEventListener('click', async () => {
      const newName = prompt(`Rename "${name}" to:`, name);
      if (!newName || !newName.trim() || newName.trim() === name) return;
      const res = await fetch(`/api/faces/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName.trim() }),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(`Rename failed: ${err.detail ?? 'Unknown error'}`);
        return;
      }
      loadFaceList();
    });

    item.querySelector('.zone-delete').addEventListener('click', async () => {
      await fetch(`/api/faces/${encodeURIComponent(name)}`, { method: 'DELETE' });
      loadFaceList();
    });

    faceList.appendChild(item);
  });
}

btnEnrollFace.addEventListener('click', async () => {
  const name = prompt('Enter a name for this face:');
  if (!name || !name.trim()) return;
  try {
    const res  = await fetch('/api/faces/enroll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(`Enrollment failed: ${data.detail ?? 'Unknown error'}`);
      return;
    }
    console.info('Enrolled face:', data.name);
    loadFaceList();
  } catch (e) {
    console.warn('Enrollment request failed', e);
  }
});

// ── Face notification settings modal ─────────────────────────────────────────

const fsOverlay        = document.getElementById('face-settings-overlay');
const fsFaceName       = document.getElementById('fs-face-name');
const fsNotifyEnabled  = document.getElementById('fs-notify-enabled');
const fsTelegram       = document.getElementById('fs-telegram-msg');
const fsEmail          = document.getElementById('fs-email-msg');
const btnFsSave        = document.getElementById('btn-face-settings-save');
const btnFsCancel      = document.getElementById('btn-face-settings-cancel');
const btnFsClose       = document.getElementById('btn-face-settings-close');

let _fsCurrentFace = null;

function closeFaceSettings() {
  fsOverlay.classList.add('hidden');
  _fsCurrentFace = null;
}

async function openFaceSettings(name) {
  _fsCurrentFace = name;
  fsFaceName.textContent  = name;
  fsNotifyEnabled.checked = true;
  fsTelegram.value        = '';
  fsEmail.value           = '';

  try {
    const res  = await fetch(`/api/faces/${encodeURIComponent(name)}/settings`);
    const data = await res.json();
    fsNotifyEnabled.checked = data.notify_enabled !== false;
    fsTelegram.value        = data.telegram_message ?? '';
    fsEmail.value           = data.email_message    ?? '';
  } catch (e) {
    console.warn('[faces] failed to load face settings', e);
  }

  fsOverlay.classList.remove('hidden');
  fsTelegram.focus();
}

btnFsSave.addEventListener('click', async () => {
  if (!_fsCurrentFace) return;
  try {
    await fetch(`/api/faces/${encodeURIComponent(_fsCurrentFace)}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notify_enabled:   fsNotifyEnabled.checked,
        telegram_message: fsTelegram.value.trim(),
        email_message:    fsEmail.value.trim(),
      }),
    });
  } catch (e) {
    console.error('[faces] failed to save face settings', e);
  }
  // Refresh the profiles list so the bell icon reflects the new state
  loadFaceList();
  closeFaceSettings();
});

btnFsCancel.addEventListener('click', closeFaceSettings);
btnFsClose.addEventListener('click',  closeFaceSettings);
fsOverlay.addEventListener('click', (e) => { if (e.target === fsOverlay) closeFaceSettings(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !fsOverlay.classList.contains('hidden')) closeFaceSettings();
});

// ── Face model loading indicator ──────────────────────────────────────────────

const faceLoading      = document.getElementById('face-loading');
const faceLoadingLabel = document.getElementById('face-loading-label');
const faceSection      = document.getElementById('section-faces');

window.addEventListener('vip:event', (e) => {
  const { type, model, name, similarity } = e.detail ?? {};
  if (type === 'face_model_loading') {
    faceLoadingLabel.textContent = `Loading ${model ?? 'model'}…`;
    faceLoading.classList.remove('hidden');
    const body = faceSection.querySelector('.feature-body');
    if (body) body.classList.remove('collapsed');
  } else if (type === 'face_model_ready' || type === 'face_model_error') {
    faceLoading.classList.add('hidden');
  } else if (type === 'face_recognized') {
    console.info(`Face recognised: ${name} (${Math.round((similarity ?? 0) * 100)}%)`);
  } else if (type === 'face_enrolled') {
    // Auto-enrolled — refresh the list; if the profiles modal is open it updates live
    loadFaceList();
  }
});

// ── Populate UI from server config on load ────────────────────────────────────

async function loadConfig() {
  const url = _streamConfigUrl();
  if (!url) return;
  try {
    const res  = await fetch(url);
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

    // Zones
    if (data.notify_on_zone_trigger !== undefined) {
      zoneNotifToggle.checked = data.notify_on_zone_trigger;
    }

    // Detection
    detToggle.checked = data.enable_detection;
    if (data.yolo_model)     detModel.value = data.yolo_model;
    if (data.yolo_confidence !== undefined) {
      detConfidence.value = Math.round(data.yolo_confidence * 100);
      detConfidenceVal.textContent = `${detConfidence.value}%`;
    }
    if (data.yolo_skip_frames !== undefined) {
      detSkip.value = data.yolo_skip_frames;
      detSkipVal.textContent = `${data.yolo_skip_frames}f`;
    }
    if (data.detect_classes !== undefined) detClasses.value = data.detect_classes;

    // Face recognition — sidebar toggles only; modal fields populate on open
    faceToggle.checked = data.enable_faces ?? false;
    if (data.notify_on_face_recognized !== undefined && faceNotifToggle) {
      faceNotifToggle.checked = data.notify_on_face_recognized;
    }

    // License plates
    if (data.enable_plates !== undefined) platesToggle.checked = data.enable_plates;
    if (data.plate_confidence !== undefined) {
      plateConfidence.value = Math.round(data.plate_confidence * 100);
      plateConfidenceVal.textContent = `${plateConfidence.value}%`;
    }
    if (data.plate_skip_frames !== undefined) {
      plateSkip.value = data.plate_skip_frames;
      plateSkipVal.textContent = `${data.plate_skip_frames}f`;
    }
    if (data.plate_save_screenshot !== undefined) plateScreenshot.checked = data.plate_save_screenshot;
    if (data.notify_on_plate_detected !== undefined) plateNotif.checked = data.notify_on_plate_detected;

  } catch (e) {
    console.warn('failed to load config', e);
  }
}

window.loadConfig = loadConfig;  // called by stream.js on tab switch
// loadConfig() is called by stream.js after activeStreamId is set


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
  const url = _streamConfigUrl() ?? '/api/config';
  fetch(url)
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
  const sid = window.activeStreamId;
  const statusUrl = sid ? `/api/streams/${sid}/status` : '/api/status';
  const configUrl = _streamConfigUrl() ?? '/api/config';
  const streamsUrl = '/api/streams';
  const [statusRes, configRes, streamsRes] = await Promise.all([
    fetch(statusUrl),
    fetch(configUrl),
    fetch(streamsUrl),
  ]);
  const status  = await statusRes.json();
  const config  = await configRes.json();
  const streams = await streamsRes.json();

  // URL comes from the stream registration, not the pipeline config
  const thisStream = (streams.streams ?? []).find(s => s.id === sid);
  ssSource.value = thisStream?.url ?? status.source ?? '';

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
  const sid = window.activeStreamId;
  const newUrl = ssSource.value.trim();

  // URL is a stream-registration property — must go through PATCH /api/streams/{id}
  if (sid && newUrl) {
    try {
      await fetch(`/api/streams/${sid}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: newUrl }),
      });
    } catch (e) {
      console.warn('Failed to update stream URL', e);
    }
  }

  // FPS and quality are per-channel pipeline config
  await patchConfig({
    target_fps:   parseInt(ssFps.value),
    jpeg_quality: parseInt(ssQuality.value),
  });

  closeStreamSettings();
});


// ── General Settings Modal ────────────────────────────────────────────────────

// ── Stream Registry ───────────────────────────────────────────────────────────

const gsStreamList  = document.getElementById('gs-stream-list');
const gsStreamCount = document.getElementById('gs-stream-count');
const gsStreamForm  = document.getElementById('gs-stream-form');
const gsSfCh        = document.getElementById('gs-sf-ch');
const gsSfName      = document.getElementById('gs-sf-name');
const gsSfUrl       = document.getElementById('gs-sf-url');
const btnAddStream  = document.getElementById('btn-add-stream');
const btnSfCancel   = document.getElementById('btn-sf-cancel');
const btnSfSave     = document.getElementById('btn-sf-save');

const MAX_STREAMS = 4;
let _editingStreamId = null;   // null = adding, number = editing
const gsSfError = document.getElementById('gs-sf-error');

function _showStreamError(msg) {
  gsSfError.textContent = msg;
  gsSfError.classList.remove('hidden');
}
function _clearStreamError() {
  gsSfError.textContent = '';
  gsSfError.classList.add('hidden');
}

function renderStreams(streams) {
  gsStreamList.innerHTML = '';
  gsStreamCount.textContent = `(${streams.length} / ${MAX_STREAMS})`;
  btnAddStream.disabled = streams.length >= MAX_STREAMS;

  streams.forEach(s => {
    const row = document.createElement('div');
    row.className = 'stream-item';
    row.dataset.id = s.id;
    row.innerHTML = `
      <span class="stream-ch">CH${s.channel_number}</span>
      <span class="stream-name">${s.name}</span>
      <span class="stream-url">${s.url}</span>
      <button class="stream-edit-btn" title="Edit">✎</button>
      <button class="stream-delete-btn" title="Remove">&times;</button>`;

    row.querySelector('.stream-edit-btn').addEventListener('click', () => openStreamForm(s));
    row.querySelector('.stream-delete-btn').addEventListener('click', () => deleteStream(s.id));
    gsStreamList.appendChild(row);
  });
}

async function loadStreams() {
  try {
    const res = await fetch('/api/streams');
    const data = await res.json();
    renderStreams(data.streams ?? []);
  } catch (e) {
    console.warn('failed to load streams', e);
  }
}

function openStreamForm(stream = null) {
  _editingStreamId = stream ? stream.id : null;
  gsSfCh.value   = stream ? stream.channel_number : '';
  gsSfName.value = stream ? stream.name : '';
  gsSfUrl.value  = stream ? stream.url  : '';
  gsStreamForm.classList.remove('hidden');
  btnAddStream.classList.add('hidden');
  gsSfName.focus();
}

function closeStreamForm() {
  gsStreamForm.classList.add('hidden');
  btnAddStream.classList.remove('hidden');
  _editingStreamId = null;
  _clearStreamError();
}

async function deleteStream(id) {
  if (!confirm('Remove this stream?')) return;
  await fetch(`/api/streams/${id}`, { method: 'DELETE' });
  await loadStreams();
  await window.loadStreamTabs?.();
}

btnAddStream.addEventListener('click', () => openStreamForm());
btnSfCancel.addEventListener('click', closeStreamForm);

btnSfSave.addEventListener('click', async () => {
  const ch   = parseInt(gsSfCh.value);
  const name = gsSfName.value.trim();
  const url  = gsSfUrl.value.trim();

  if (!name || !url || isNaN(ch)) return;
  _clearStreamError();

  let res;
  if (_editingStreamId !== null) {
    res = await fetch(`/api/streams/${_editingStreamId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_number: ch, name, url }),
    });
  } else {
    res = await fetch('/api/streams', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_number: ch, name, url }),
    });
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    _showStreamError(err.detail ?? 'Failed to save stream.');
    return;
  }

  closeStreamForm();
  await loadStreams();
  await window.loadStreamTabs?.();
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
  closeStreamForm();
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    gsOutputDir.value       = cfg.recording_output_dir       ?? '';
    gsProjectName.value     = cfg.recording_project_name     ?? '';
    gsFilenamePattern.value = cfg.recording_filename_pattern ?? '';
  } catch (e) {
    console.warn('failed to load general settings', e);
  }
  await loadStreams();
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
  await patchGlobalConfig({
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

function _recordingBase() {
  const sid = window.activeStreamId;
  return sid ? `/api/streams/${sid}/recording` : '/api/recording';
}

btnRecord.addEventListener('click', async () => {
  if (_recordingActive) {
    // Stop
    try {
      const res  = await fetch(`${_recordingBase()}/stop`, { method: 'POST' });
      const data = await res.json();
      console.info('Recording saved to', data.saved_to);
    } catch (e) {
      console.warn('Failed to stop recording', e);
    }
    _setRecordingState(false);
  } else {
    // Start
    try {
      const res = await fetch(`${_recordingBase()}/start`, { method: 'POST' });
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
    const res = await fetch(`${_recordingBase()}/screenshot`, { method: 'POST' });
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


// ── License Plates ────────────────────────────────────────────────────────────

const platesToggle       = document.getElementById('toggle-plates');
const plateConfidence    = document.getElementById('plate-confidence');
const plateConfidenceVal = document.getElementById('plate-confidence-val');
const plateSkip          = document.getElementById('plate-skip');
const plateSkipVal       = document.getElementById('plate-skip-val');
const plateScreenshot    = document.getElementById('toggle-plate-screenshot');
const plateNotif         = document.getElementById('toggle-plate-notif');
const plateLoading       = document.getElementById('plate-loading');
const plateLoadingLabel  = document.getElementById('plate-loading-label');
const plateSection       = document.getElementById('section-plates');

platesToggle.addEventListener('change', () => {
  patchConfig({ enable_plates: platesToggle.checked });
});

plateConfidence.addEventListener('input', () => {
  plateConfidenceVal.textContent = `${plateConfidence.value}%`;
});
plateConfidence.addEventListener('input', debounce(() => {
  patchConfig({ plate_confidence: parseInt(plateConfidence.value) / 100 });
}, DEBOUNCE_MS));

plateSkip.addEventListener('input', () => {
  plateSkipVal.textContent = `${plateSkip.value}f`;
});
plateSkip.addEventListener('input', debounce(() => {
  patchConfig({ plate_skip_frames: parseInt(plateSkip.value) });
}, DEBOUNCE_MS));

plateScreenshot.addEventListener('change', () => {
  patchConfig({ plate_save_screenshot: plateScreenshot.checked });
});

plateNotif.addEventListener('change', () => {
  patchConfig({ notify_on_plate_detected: plateNotif.checked });
});

// Model loading indicator
window.addEventListener('vip:event', (e) => {
  const { type, model, plate, plate_norm, list_status } = e.detail ?? {};
  if (type === 'plate_model_loading') {
    plateLoadingLabel.textContent = `Loading plate model…`;
    plateLoading.classList.remove('hidden');
    const body = plateSection.querySelector('.feature-body');
    if (body) body.classList.remove('collapsed');
  } else if (type === 'plate_model_ready' || type === 'plate_model_error') {
    plateLoading.classList.add('hidden');
  } else if (type === 'plate_detected') {
    console.info(`Plate detected: ${plate} (${plate_norm}) — ${list_status}`);
  }
});

// ── Plate Allow / Block List Modal ────────────────────────────────────────────

const plateListOverlay = document.getElementById('plate-list-overlay');
const btnPlateList     = document.getElementById('btn-plate-list');
const btnPlateListClose = document.getElementById('btn-plate-list-close');
const btnPlateListDone  = document.getElementById('btn-plate-list-done');
const plEntriesEl       = document.getElementById('plate-list-entries');
const plPlateText       = document.getElementById('pl-plate-text');
const plNotes           = document.getElementById('pl-notes');
const plError           = document.getElementById('pl-error');
const btnPlAdd          = document.getElementById('btn-pl-add');

function _plListType() {
  return document.querySelector('input[name="pl-type"]:checked')?.value ?? 'allow';
}

async function loadPlateList() {
  try {
    const res  = await fetch('/api/plates/list');
    const data = await res.json();
    renderPlateList(data.entries ?? []);
  } catch (e) {
    console.warn('[plates] failed to load list', e);
  }
}

function renderPlateList(entries) {
  plEntriesEl.innerHTML = '';
  if (entries.length === 0) {
    plEntriesEl.innerHTML = '<p class="field-hint" style="margin-top:0.5rem">No entries yet.</p>';
    return;
  }
  entries.forEach(({ plate_text_norm, plate_text_raw, list_type, notes }) => {
    const row = document.createElement('div');
    row.className = 'plate-list-row';
    const badge = list_type === 'target'
      ? '<span class="plate-badge plate-badge--target">target</span>'
      : '<span class="plate-badge plate-badge--allowed">allowed</span>';
    row.innerHTML = `
      ${badge}
      <span class="plate-list-text">${plate_text_raw}</span>
      ${notes ? `<span class="plate-list-notes">${notes}</span>` : ''}
      <button class="face-item-btn zone-delete plate-list-del" data-norm="${plate_text_norm}" title="Remove">&times;</button>`;
    row.querySelector('.plate-list-del').addEventListener('click', async (e) => {
      const norm = e.currentTarget.dataset.norm;
      await fetch(`/api/plates/list/${encodeURIComponent(norm)}`, { method: 'DELETE' });
      loadPlateList();
    });
    plEntriesEl.appendChild(row);
  });
}

function openPlateList() {
  loadPlateList();
  plateListOverlay.classList.remove('hidden');
}
function closePlateList() {
  plateListOverlay.classList.add('hidden');
  plError.style.display = 'none';
}

btnPlateList.addEventListener('click', openPlateList);
btnPlateListClose.addEventListener('click', closePlateList);
btnPlateListDone.addEventListener('click',  closePlateList);
plateListOverlay.addEventListener('click', (e) => { if (e.target === plateListOverlay) closePlateList(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !plateListOverlay.classList.contains('hidden')) closePlateList();
});

btnPlAdd.addEventListener('click', async () => {
  const text  = plPlateText.value.trim();
  const ltype = _plListType();
  const notes = plNotes.value.trim();
  plError.style.display = 'none';
  if (!text) { plError.textContent = 'Enter a plate number.'; plError.style.display = ''; return; }
  try {
    const res = await fetch('/api/plates/list', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plate_text: text, list_type: ltype, notes }),
    });
    if (!res.ok) {
      const err = await res.json();
      plError.textContent = err.detail ?? 'Failed to add plate.';
      plError.style.display = '';
      return;
    }
    plPlateText.value = '';
    plNotes.value = '';
    loadPlateList();
  } catch (e) {
    plError.textContent = 'Network error.';
    plError.style.display = '';
  }
});

// ── Recent Plate Events Modal ─────────────────────────────────────────────────

const plateEventsOverlay = document.getElementById('plate-events-overlay');
const btnPlateEvents     = document.getElementById('btn-plate-events');
const btnPlateEventsClose = document.getElementById('btn-plate-events-close');
const btnPlateEventsDone  = document.getElementById('btn-plate-events-done');
const plateEventsList     = document.getElementById('plate-events-list');

async function loadPlateEvents() {
  const sid = window.activeStreamId;
  const url  = sid ? `/api/plates/events?stream_id=${sid}&limit=50` : '/api/plates/events?limit=50';
  try {
    const res  = await fetch(url);
    const data = await res.json();
    renderPlateEvents(data.events ?? []);
  } catch (e) {
    console.warn('[plates] failed to load events', e);
  }
}

function renderPlateEvents(events) {
  plateEventsList.innerHTML = '';
  if (events.length === 0) {
    plateEventsList.innerHTML = '<p class="field-hint" style="margin-top:0.5rem">No detections yet.</p>';
    return;
  }
  events.forEach(({ plate_text, plate_text_norm, confidence, detected_at, screenshot_path }) => {
    const row = document.createElement('div');
    row.className = 'plate-event-row';
    const dt = new Date(detected_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
    row.innerHTML = `
      <span class="plate-event-text">${plate_text}</span>
      <span class="plate-event-conf">${Math.round(confidence * 100)}%</span>
      <span class="plate-event-time">${dt}</span>`;
    plateEventsList.appendChild(row);
  });
}

function openPlateEvents() {
  loadPlateEvents();
  plateEventsOverlay.classList.remove('hidden');
}
function closePlateEvents() {
  plateEventsOverlay.classList.add('hidden');
}

btnPlateEvents.addEventListener('click', openPlateEvents);
btnPlateEventsClose.addEventListener('click', closePlateEvents);
btnPlateEventsDone.addEventListener('click',  closePlateEvents);
plateEventsOverlay.addEventListener('click', (e) => { if (e.target === plateEventsOverlay) closePlateEvents(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !plateEventsOverlay.classList.contains('hidden')) closePlateEvents();
});

// ── Sync recording state on page load (in case server was already recording)
fetch(_recordingBase() + '/status')
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
