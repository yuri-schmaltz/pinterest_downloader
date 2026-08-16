// Service Worker — orchestrates a download queue for the Pinterest downloader.
// Receives harvest results from content.js / popup.js and dispatches them via
// chrome.downloads with bounded concurrency, error handling, and per-file
// filename safety.

// ===================== Queue State =====================

const MAX_CONCURRENT = 6;
let activeDownloads = 0;
const downloadQueue = [];

// ===================== Filename Helpers =====================

/**
 * Extract a sensible file extension from a Pinterest image URL.
 * Falls back to 'jpg' when the URL has no recognizable extension.
 */
function extractExtension(url) {
  try {
    const u = new URL(url);
    const lastSegment = u.pathname.split('/').pop() || '';
    const m = /\.([a-zA-Z0-9]{2,5})$/.exec(lastSegment);
    if (m) return m[1].toLowerCase();
  } catch { /* not a valid URL */ }
  return 'jpg';
}

/**
 * Build a safe, unique filename for the download API.
 *   Pinterest_<timestamp>_<index>.<ext>
 */
function safeFilename(url, index) {
  const ext = extractExtension(url);
  return `Pinterest_${Date.now()}_${index}.${ext}`;
}

// ===================== Queue Processing =====================

function processQueue() {
  while (activeDownloads < MAX_CONCURRENT && downloadQueue.length > 0) {
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
      }
      activeDownloads = Math.max(0, activeDownloads - 1);
      processQueue();
    }
  );
}

// ===================== Message Handler =====================

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "downloadImages") {
    const urls = Array.isArray(request.urls) ? request.urls : [];

    if (urls.length === 0) {
      sendResponse({ status: "error", message: "Nenhuma URL válida encontrada." });
      return false;
    }

    let queued = 0;
    urls.forEach((item, index) => {
      if (!item || !item.url) return;
      downloadQueue.push({
        url: item.url,
        filename: safeFilename(item.url, index),
      });
      queued++;
    });

    processQueue();
    sendResponse({ status: "success", count: queued });
    return false;
  }
  return false;
});

console.log("[PBD] Service Worker loaded.");
