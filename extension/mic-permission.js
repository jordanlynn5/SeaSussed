// extension/mic-permission.js
// Opened as a tab by the side panel when mic permission is needed.
// Calls getUserMedia directly from a button-click user gesture (most reliable path),
// then notifies the side panel and closes.

const btn = document.getElementById('allow-btn');
const errEl = document.getElementById('error-msg');

btn.addEventListener('click', async () => {
  btn.disabled = true;
  btn.textContent = 'Requesting…';
  errEl.style.display = 'none';

  let stream;
  try {
    // getUserMedia must be the first await — preserves Chrome's user activation context.
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Allow Microphone';
    errEl.style.display = 'block';
    if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError') {
      errEl.textContent = 'Microphone access was denied. Allow it in Chrome → Settings → Privacy and Security → Site Settings → Microphone.';
    } else if (e.name === 'NotFoundError' || e.name === 'DevicesNotFoundError') {
      errEl.innerHTML = 'No microphone found. On Mac: <strong>System Settings → Privacy &amp; Security → Microphone</strong> → enable Google Chrome, then reload.';
    } else {
      errEl.textContent = `Could not access microphone: ${e.message}`;
    }
    return;
  }

  // Stop immediately — the side panel will call getUserMedia again when starting voice.
  // We only needed the permission grant; the stream itself isn't passed across tabs.
  stream.getTracks().forEach(t => t.stop());

  // Notify the side panel and close this tab.
  chrome.runtime.sendMessage({ type: 'MIC_PERMISSION_GRANTED' });
  window.close();
});
