// Popup UI — connects to the content script via chrome.scripting.executeScript,
// and lets the user configure folder / concurrency via chrome.storage.

(function () {
  'use strict';

  const i18n = window.__pbdI18n || { t: (k, ...args) => (args.length ? k.replace(/\$(\d+)\$/g, (m, n) => args[parseInt(n, 10) - 1] || m) : k) };
  const T = (k, ...args) => i18n.t(k, ...args);

  function getVersion() {
    try {
      return (chrome.runtime && chrome.runtime.getManifest) ? chrome.runtime.getManifest().version : '2.0.0';
    } catch { return '2.0.0'; }
  }

  function applyI18n() {
    document.getElementById('popup-title').textContent = T('popup_title');
    document.getElementById('download-btn').textContent = T('popup_button');
    document.getElementById('label-folder').textContent = T('opt_folder');
    document.getElementById('label-concurrent').textContent = T('opt_concurrent');
    document.getElementById('popup-footer').textContent = T('popup_footer', getVersion());
  }

  function loadSettings(cb) {
    try {
      chrome.storage.local.get(['folder', 'maxConcurrent'], (data) => {
        if (chrome.runtime.lastError) {
          cb({ folder: 'Pinterest', maxConcurrent: 6 });
          return;
        }
        cb({
          folder: typeof data.folder === 'string' && data.folder ? data.folder : 'Pinterest',
          maxConcurrent: typeof data.maxConcurrent === 'number' ? data.maxConcurrent : 6,
        });
      });
    } catch {
      cb({ folder: 'Pinterest', maxConcurrent: 6 });
    }
  }

  function saveSettings(settings) {
    try {
      chrome.storage.local.set(settings);
    } catch { /* ignore */ }
  }

  document.addEventListener('DOMContentLoaded', () => {
    applyI18n();

    const folderInput = document.getElementById('opt-folder');
    const concurrentInput = document.getElementById('opt-concurrent');
    const statusEl = document.getElementById('status');
    const downloadBtn = document.getElementById('download-btn');

    loadSettings((s) => {
      folderInput.value = s.folder;
      concurrentInput.value = s.maxConcurrent;
    });

    let saveTimer = null;
    function scheduleSave() {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        saveSettings({
          folder: folderInput.value.trim() || 'Pinterest',
          maxConcurrent: Math.max(1, Math.min(12, parseInt(concurrentInput.value, 10) || 6)),
        });
        statusEl.textContent = T('status_saved', '');
      }, 400);
    }
    folderInput.addEventListener('input', scheduleSave);
    concurrentInput.addEventListener('input', scheduleSave);

    downloadBtn.addEventListener('click', () => {
      saveSettings({
        folder: folderInput.value.trim() || 'Pinterest',
        maxConcurrent: Math.max(1, Math.min(12, parseInt(concurrentInput.value, 10) || 6)),
      });

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

        chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => {
            const btn = document.getElementById('pinterest-pro-toolbar');
            if (btn) btn.click();
            else return 'no-toolbar';
          },
        }, () => {
          setTimeout(() => {
            downloadBtn.disabled = false;
            statusEl.textContent = T('status_triggered');
          }, 1500);
        });
      });
    });
  });
})();
