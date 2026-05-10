/**
 * Service Worker (Background) — Orchestrates downloads.
 * Receives resolved image URLs from content script/popup
 * and uses chrome.downloads API to save files.
 */

// ========== Download Queue ==========

const MAX_CONCURRENT = 6;
let activeDownloads = 0;
const downloadQueue = [];
let totalQueued = 0;
let totalCompleted = 0;
let totalFailed = 0;
let currentBoardUrl = "";
let isCancelled = false;

/**
 * Enqueue a download job.
 */
function enqueueDownload(imageUrl, filename, boardUrl) {
  downloadQueue.push({ imageUrl, filename, boardUrl });
  totalQueued++;
  processQueue();
}

/**
 * Process the download queue, respecting concurrency limits.
 */
function processQueue() {
  if (isCancelled) return;

  while (activeDownloads < MAX_CONCURRENT && downloadQueue.length > 0) {
    const job = downloadQueue.shift();
    activeDownloads++;
    executeDownload(job);
  }
}

/**
 * Execute a single download via chrome.downloads API.
 */
async function executeDownload(job) {
  try {
    const downloadId = await new Promise((resolve, reject) => {
      chrome.downloads.download(
        {
          url: job.imageUrl,
          filename: job.filename,
          conflictAction: "uniquify",
          saveAs: false,
        },
        (id) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(id);
          }
        }
      );
    });

    // Wait for download to complete
    await waitForDownload(downloadId);
    totalCompleted++;
  } catch (err) {
    console.warn("[PBD] Download failed:", job.imageUrl, err.message);
    totalFailed++;
  } finally {
    activeDownloads--;
    broadcastProgress();
    processQueue();

    // Check if all done
    if (activeDownloads === 0 && downloadQueue.length === 0) {
      broadcastComplete();
    }
  }
}

/**
 * Wait for a chrome download to complete.
 */
function waitForDownload(downloadId) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error("Download timeout"));
    }, 120000); // 2 min timeout

    function onChange(delta) {
      if (delta.id !== downloadId) return;

      if (delta.state) {
        if (delta.state.current === "complete") {
          clearTimeout(timeout);
          chrome.downloads.onChanged.removeListener(onChange);
          resolve();
        } else if (delta.state.current === "interrupted") {
          clearTimeout(timeout);
          chrome.downloads.onChanged.removeListener(onChange);
          reject(new Error("Download interrupted"));
        }
      }
    }

    chrome.downloads.onChanged.addListener(onChange);
  });
}

// ========== Progress Broadcasting ==========

function broadcastProgress() {
  chrome.runtime.sendMessage({
    type: "DOWNLOAD_PROGRESS",
    completed: totalCompleted,
    failed: totalFailed,
    total: totalQueued,
    active: activeDownloads,
    queued: downloadQueue.length,
    boardUrl: currentBoardUrl,
  }).catch(() => {});
}

function broadcastComplete() {
  chrome.runtime.sendMessage({
    type: "DOWNLOAD_COMPLETE",
    completed: totalCompleted,
    failed: totalFailed,
    total: totalQueued,
    boardUrl: currentBoardUrl,
  }).catch(() => {});
}

// ========== Slugify (duplicated for service worker context) ==========

function slugify(name) {
  if (typeof name !== "string") name = String(name);
  try { name = decodeURIComponent(name); } catch {}
  name = name.normalize("NFC");
  name = name.replace(/\u00A0/g, " ");
  name = name.replace(/[\n\r\t]/g, " ");
  name = name.replace(/\s+/g, " ").trim();
  name = name.replace(/\//g, "／").replace(/\x00/g, "");
  return name || "sem_nome";
}

function safeName(url) {
  const m = /\/pin\/(\d+)\/?/.exec(url);
  if (m) return `${m[1]}.jpg`;
  try {
    const parts = new URL(url).pathname.split("/");
    let base = parts[parts.length - 1] || "";
    base = base.split("?")[0];
    if (!base || !base.includes(".")) {
      let hash = 0;
      for (let i = 0; i < url.length; i++) {
        hash = ((hash << 5) - hash) + url.charCodeAt(i);
        hash |= 0;
      }
      base = Math.abs(hash).toString(16) + ".jpg";
    }
    return base;
  } catch {
    return Date.now() + ".jpg";
  }
}

function splitUserBoard(boardUrl) {
  try {
    const u = new URL(boardUrl);
    const parts = u.pathname.split("/").filter(Boolean);
    return {
      user: decodeURIComponent(parts[0] || "user"),
      board: decodeURIComponent(parts[1] || "board"),
    };
  } catch {
    return { user: "user", board: "board" };
  }
}

// ========== Message Handler ==========

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case "START_DOWNLOADS": {
      // msg: { boardUrl, images: { pinUrl: imageUrl, ... } }
      isCancelled = false;
      totalQueued = 0;
      totalCompleted = 0;
      totalFailed = 0;
      activeDownloads = 0;
      downloadQueue.length = 0;
      currentBoardUrl = msg.boardUrl || "";

      const { user, board } = splitUserBoard(msg.boardUrl);
      const folder = `Pinterest/${slugify(user)}/${slugify(board)}`;

      const images = msg.images || {};
      for (const [pinUrl, imageUrl] of Object.entries(images)) {
        const name = safeName(pinUrl);
        enqueueDownload(imageUrl, `${folder}/${name}`, msg.boardUrl);
      }

      sendResponse({
        ok: true,
        total: totalQueued,
        folder,
      });
      return false;
    }

    case "CANCEL_DOWNLOADS": {
      isCancelled = true;
      downloadQueue.length = 0;
      sendResponse({
        ok: true,
        completed: totalCompleted,
        cancelled: totalQueued - totalCompleted - totalFailed,
      });
      return false;
    }

    case "GET_DOWNLOAD_STATUS": {
      sendResponse({
        completed: totalCompleted,
        failed: totalFailed,
        total: totalQueued,
        active: activeDownloads,
        queued: downloadQueue.length,
        boardUrl: currentBoardUrl,
        cancelled: isCancelled,
      });
      return false;
    }

    // Cache management via chrome.storage.local
    case "CACHE_GET": {
      chrome.storage.local.get("pinCache", (data) => {
        sendResponse(data.pinCache || {});
      });
      return true;
    }

    case "CACHE_SET": {
      chrome.storage.local.get("pinCache", (data) => {
        const cache = data.pinCache || {};
        Object.assign(cache, msg.entries || {});
        chrome.storage.local.set({ pinCache: cache }, () => {
          sendResponse({ ok: true });
        });
      });
      return true;
    }

    default:
      return false;
  }
});

console.log("[PBD] Service Worker loaded.");
