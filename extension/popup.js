// Popup UI — connects to the content script via chrome.scripting.executeScript,
// and lets the user configure folder, max-pins limit and concurrency.

(function () {
  'use strict';

  const i18n = window.__pbdI18n || { t: (k, ...args) => (args.length ? k.replace(/\$(\d+)\$/g, (m, n) => args[parseInt(n, 10) - 1] || m) : k) };
  const T = (k, ...args) => i18n.t(k, ...args);

  const SETTINGS_KEYS = ['folder', 'maxConcurrent', 'maxPins'];

  function getVersion() {
    try {
      return (chrome.runtime && chrome.runtime.getManifest) ? chrome.runtime.getManifest().version : '2.0.0';
    } catch { return '2.0.0'; }
  }

  function applyI18n() {
    document.getElementById('popup-title').textContent = T('popup_title');
    document.getElementById('download-btn').textContent = T('popup_button');
    document.getElementById('label-folder').textContent = T('opt_folder');
    document.getElementById('label-max-pins').textContent = T('opt_max_pins');
    document.getElementById('label-concurrent').textContent = T('opt_concurrent');
    document.getElementById('hint-max-pins').textContent = T('opt_max_pins_hint');
    document.getElementById('popup-footer').textContent = T('popup_footer', getVersion());
    document.getElementById('pick-folder-btn').title = T('pick_folder_title');
  }

  function loadSettings(cb) {
    try {
      chrome.storage.local.get(SETTINGS_KEYS, (data) => {
        if (chrome.runtime.lastError) {
          cb(defaults());
          return;
        }
        cb({
          folder: typeof data.folder === 'string' && data.folder ? data.folder : 'Pinterest',
          maxConcurrent: typeof data.maxConcurrent === 'number' && data.maxConcurrent >= 1 && data.maxConcurrent <= 12 ? data.maxConcurrent : 6,
          maxPins: typeof data.maxPins === 'number' && data.maxPins >= 0 && data.maxPins <= 9999 ? data.maxPins : 0,
        });
      });
    } catch {
      cb(defaults());
    }
  }

  function defaults() {
    return { folder: 'Pinterest', maxConcurrent: 6, maxPins: 0 };
  }

  function saveSettings(settings) {
    try {
      chrome.storage.local.set(settings);
    } catch { /* ignore */ }
  }

  function updateFolderPreview(folder) {
    const clean = (folder || 'Pinterest').replace(/^\/+|\/+$/g, '') || 'Pinterest';
    document.getElementById('folder-preview').textContent = 'Downloads/' + clean + '/';
  }

  document.addEventListener('DOMContentLoaded', () => {
    applyI18n();

    const folderInput = document.getElementById('opt-folder');
    const maxPinsInput = document.getElementById('opt-max-pins');
    const concurrentInput = document.getElementById('opt-concurrent');
    const pickFolderBtn = document.getElementById('pick-folder-btn');
    const statusEl = document.getElementById('status');
    const downloadBtn = document.getElementById('download-btn');

    // ============ Load saved settings ============
    loadSettings((s) => {
      folderInput.value = s.folder;
      concurrentInput.value = s.maxConcurrent;
      maxPinsInput.value = s.maxPins;
      updateFolderPreview(s.folder);
    });

    // ============ Auto-save on change ============
    let saveTimer = null;
    function scheduleSave() {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const settings = collectSettings();
        saveSettings(settings);
        updateFolderPreview(settings.folder);
        statusEl.textContent = T('status_saved', '');
      }, 400);
    }
    folderInput.addEventListener('input', scheduleSave);
    maxPinsInput.addEventListener('input', scheduleSave);
    concurrentInput.addEventListener('input', scheduleSave);

    // ============ Folder picker (if browser supports it) ============
    pickFolderBtn.addEventListener('click', () => {
      // Chrome doesn't have showDirectoryPicker in MV3 (yet).
      // Firefox 121+ has it.
      try {
        if (typeof window.showDirectoryPicker === 'function') {
          window.showDirectoryPicker({ mode: 'readwrite' })
            .then(async (dirHandle) => {
              // Use the directory's name as the folder setting.
              // chrome.downloads will then create a subfolder with this name under Downloads/.
              const name = dirHandle.name || 'Pinterest';
              folderInput.value = name;
              scheduleSave();
              statusEl.textContent = T('folder_selected', name);
            })
            .catch((err) => {
              if (err.name !== 'AbortError') {
                statusEl.textContent = T('folder_pick_failed', err.message);
              }
            });
          return;
        }
      } catch { /* fall through */ }

      // Fallback: prompt user to type folder name manually
      folderInput.focus();
      folderInput.select();
      statusEl.textContent = T('folder_pick_fallback');
    });

    // ============ Main download button ============
    downloadBtn.addEventListener('click', () => {
      const settings = collectSettings();
      saveSettings(settings);

      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        const tab = tabs[0];
        if (!tab || !tab.id) {
          statusEl.textContent = T('status_no_tab');
          return;
        }
        if (!tab.url || !tab.url.includes('pinterest.com')) {
          statusEl.textContent = T('status_wrong_site');
          return;
        }

        downloadBtn.disabled = true;
        statusEl.textContent = T('status_triggering');

        // Send the harvest trigger with the current settings.
        // Content script reads maxPins via the triggerSettings event below.
        chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: triggerHarvestWithSettings,
          args: [settings],
        }, () => {
          setTimeout(() => {
            downloadBtn.disabled = false;
            statusEl.textContent = T('status_triggered');
          }, 1500);
        });
      });
    });
  });

  function collectSettings() {
    const folderRaw = document.getElementById('opt-folder').value.trim();
    const folder = folderRaw || 'Pinterest';
    const maxConcurrent = Math.max(1, Math.min(12, parseInt(document.getElementById('opt-concurrent').value, 10) || 6));
    const maxPins = Math.max(0, Math.min(9999, parseInt(document.getElementById('opt-max-pins').value, 10) || 0));
    return { folder, maxConcurrent, maxPins };
  }

  // This function runs in the page context (not popup context) via executeScript.
  // It dispatches a CustomEvent that content.js listens for.
  function triggerHarvestWithSettings(settings) {
    window.dispatchEvent(new CustomEvent('pinterest-pro-trigger', { detail: settings }));
    const btn = document.getElementById('pinterest-pro-toolbar');
    if (btn) btn.click();
  }
})();