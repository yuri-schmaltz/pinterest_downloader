// Service Worker — orchestrates a download queue for the Pinterest downloader.
// Receives harvest results from content.js / popup.js and dispatches them via
// chrome.downloads with bounded concurrency, configurable folder, descriptive
// filenames, dedup, and an action-badge counter showing initiated downloads.

// ===================== Config =====================

const DEFAULT_MAX_CONCURRENT = 6;
const DEFAULT_FOLDER = 'Pinterest';
const SESSION_TS = Date.now();

// ===================== State =====================

let activeDownloads = 0;
const downloadQueue = [];
const seenHashes = new Set();

let userSettings = {
  folder: DEFAULT_FOLDER,
  maxConcurrent: DEFAULT_MAX_CONCURRENT,
};

let downloadCount = 0;

function refreshBadge() {
  try {
    if (typeof chrome === 'undefined' || !chrome.action || !chrome.action.setBadgeText) return;
    const text = downloadCount > 0 ? String(downloadCount > 99 ? '99+' : downloadCount) : '';
    chrome.action.setBadgeText({ text });
    chrome.action.setBadgeBackgroundColor({ color: '#e60023' });
  } catch (e) { /* badge API may be unavailable in some browsers */ }
}

// ===================== Storage =====================

function loadSettings() {
  try {
    chrome.storage.local.get(['folder', 'maxConcurrent'], (data) => {
      if (chrome.runtime.lastError) return;
      if (typeof data.folder === 'string' && data.folder.length > 0 && data.folder.length <= 100) {
        userSettings.folder = data.folder;
      }
      if (typeof data.maxConcurrent === 'number' && data.maxConcurrent >= 1 && data.maxConcurrent <= 12) {
        userSettings.maxConcurrent = data.maxConcurrent;
      }
    });
  } catch { /* ignore */ }
}
loadSettings();
try {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.folder) userSettings.folder = changes.folder.newValue || DEFAULT_FOLDER;
    if (changes.maxConcurrent) userSettings.maxConcurrent = changes.maxConcurrent.newValue || DEFAULT_MAX_CONCURRENT;
  });
} catch { /* storage API not available in some browsers */ }

// ===================== Filename Helpers =====================

function extractExtension(url) {
  try {
    const u = new URL(url);
    const lastSegment = u.pathname.split('/').pop() || '';
    const m = /\.([a-zA-Z0-9]{2,5})$/.exec(lastSegment);
    if (m) return m[1].toLowerCase();
  } catch { /* not a valid URL */ }
  return 'jpg';
}

function sanitizeFolderName(s) {
  if (!s || typeof s !== 'string') return DEFAULT_FOLDER;
  const cleaned = s.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').trim();
  return cleaned.slice(0, 100) || DEFAULT_FOLDER;
}

function sanitizeHost(s) {
  if (!s || typeof s !== 'string') return 'pinterest';
  return s.replace(/[^a-z0-9.-]/gi, '_').slice(0, 60) || 'pinterest';
}

function safeFilename(url, index, pinHash, sourceHost) {
  const ext = extractExtension(url);
  const folder = sanitizeFolderName(userSettings.folder);
  const host = sanitizeHost(sourceHost);
  const id = pinHash || `img_${SESSION_TS}_${index}`;
  return `${folder}/${host}/${id}.${ext}`;
}

// ===================== Queue Processing =====================

function processQueue() {
  const max = userSettings.maxConcurrent || DEFAULT_MAX_CONCURRENT;
  while (activeDownloads < max && downloadQueue.length > 0) {
    const job = downloadQueue.shift();
    activeDownloads++;
    executeDownload(job);
  }
}

function executeDownload(job) {
  chrome.downloads.download(
    {
      url: job.url,
      filename: job.filename,
      conflictAction: 'uniquify',
      saveAs: false,
    },
    (downloadId) => {
      if (chrome.runtime.lastError) {
        console.warn(`[PBD] Download failed: ${job.url}`, chrome.runtime.lastError.message);
      } else {
        console.log(`[PBD] Download started: id=${downloadId} url=${job.url}`);
        downloadCount++;
        refreshBadge();
      }
      activeDownloads = Math.max(0, activeDownloads - 1);
      processQueue();
    }
  );
}

// ===================== Message Handler =====================

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'downloadImages') {
    const urls = Array.isArray(request.urls) ? request.urls : [];
    let sourceHost = request.source;
    if (!sourceHost && sender.url) {
      try { sourceHost = new URL(sender.url).hostname; } catch { sourceHost = 'pinterest'; }
    }
    if (!sourceHost) sourceHost = 'pinterest';

    // Per-request overrides fall back to stored settings.
    const folderOverride = typeof request.folder === 'string' && request.folder
      ? request.folder : userSettings.folder;
    const maxOverride = typeof request.maxConcurrent === 'number'
      && request.maxConcurrent >= 1 && request.maxConcurrent <= 12
      ? request.maxConcurrent : userSettings.maxConcurrent;
    const previousFolder = userSettings.folder;
    const previousMax = userSettings.maxConcurrent;
    userSettings.folder = folderOverride;
    userSettings.maxConcurrent = maxOverride;

    if (urls.length === 0) {
      // Restore previous settings before responding.
      userSettings.folder = previousFolder;
      userSettings.maxConcurrent = previousMax;
      sendResponse({ status: 'error', message: 'No valid URLs found.' });
      return false;
    }

    let queued = 0;
    let skippedDupes = 0;
    urls.forEach((item, index) => {
      if (!item || !item.url) return;
      const dedupeKey = item.pinHash || item.url;
      if (seenHashes.has(dedupeKey)) {
        skippedDupes++;
        return;
      }
      seenHashes.add(dedupeKey);
      downloadQueue.push({
        url: item.url,
        filename: safeFilename(item.url, index, item.pinHash, sourceHost),
      });
      queued++;
    });

    processQueue();

    // Restore userSettings to their stored values so subsequent harvests
    // don't keep using the popup's per-request override.
    userSettings.folder = previousFolder;
    userSettings.maxConcurrent = previousMax;

    sendResponse({ status: 'success', count: queued, skipped: skippedDupes });
    return false;
  }

  if (request.action === 'getSettings') {
    sendResponse({ folder: userSettings.folder, maxConcurrent: userSettings.maxConcurrent });
    return false;
  }

  if (request.action === 'resetBadge') {
    downloadCount = 0;
    refreshBadge();
    sendResponse({ ok: true });
    return false;
  }

  return false;
});

// ===================== Lifecycle =====================

chrome.runtime.onStartup.addListener(() => {
  seenHashes.clear();
  downloadCount = 0;
  refreshBadge();
});

chrome.runtime.onInstalled.addListener(() => {
  downloadCount = 0;
  refreshBadge();
});

console.log('[PBD] Service Worker loaded.');
