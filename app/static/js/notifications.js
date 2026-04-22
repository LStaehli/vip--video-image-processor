/**
 * notifications.js — zone alert notifications
 *
 * Listens for vip:event dispatched by stream.js from the /ws/events WebSocket.
 * On a zone_alert event, adds a timestamped item to #notif-list in the sidebar.
 * Each notification auto-dismisses after 15 s; the list is capped at 10 items.
 */

const notifList  = document.getElementById('notif-list');
const MAX_NOTIFS = 10;
const NOTIF_TTL  = 15_000; // ms

window.addEventListener('vip:event', (e) => {
  const payload = e.detail;
  if (payload.type === 'zone_alert') {
    addNotification(`Zone alert: ${payload.zone}`, 'alarm');
  } else if (payload.type === 'face_recognized') {
    const pct = Math.round((payload.similarity ?? 0) * 100);
    addNotification(`Face recognised: ${payload.name} (${pct}%)`, 'face');
  } else if (payload.type === 'face_enrolled') {
    addNotification(`Auto-enrolled: ${payload.name}`, 'face');
  }
});

function addNotification(message, cls = '') {
  const item = document.createElement('div');
  item.className = `notif-item${cls ? ' ' + cls : ''}`;

  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  item.textContent = `${time}  ${message}`;

  notifList.prepend(item);

  // Auto-remove after TTL
  const timer = setTimeout(() => item.remove(), NOTIF_TTL);
  item.addEventListener('click', () => { clearTimeout(timer); item.remove(); });

  // Cap list length
  while (notifList.children.length > MAX_NOTIFS) {
    notifList.lastElementChild.remove();
  }
}
