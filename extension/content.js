(function () {
  'use strict';

  // ===================== Config =====================

  const TOOLBAR_ID = 'pinterest-pro-toolbar';
  const TOAST_ID = 'pinterest-pro-toast';
  const BADGE_ID = 'pinterest-pro-badge';
  const SCROLL_PAUSE_MS = 1500;
  const SCROLL_STABLE_ROUNDS = 6;        // require 6 stable rounds (~9s) before stopping
  const SCROLL_MIN_ROUNDS = 8;           // always scroll at least 8 times before stopping
  const SCROLL_MAX_ITERATIONS = 100;     // hard cap = ~150s = 2.5 min
  const SCROLL_MAX_DURATION_MS = 150000; // 2.5 min wall-clock cap

  const i18n = window.__pbdI18n || { t: (k) => k, getLocale: () => 'en' };
  const T = (k, ...args) => i18n.t(k, ...args);

  // ===================== State =====================

  let _busy = false;
  let _lastHarvestCount = 0;
  let _triggerSettings = null;  // settings passed in via popup CustomEvent

  // ===================== Floating Toolbar =====================

  function createFloatingToolbar() {
    if (document.getElementById(TOOLBAR_ID)) return;

    const toolbar = document.createElement('div');
    toolbar.id = TOOLBAR_ID;
    toolbar.setAttribute('role', 'button');
    toolbar.setAttribute('aria-label', T('toolbar_aria'));
    toolbar.title = T('toolbar_title');
    toolbar.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 999999;
      background: #e60023;
      color: white;
      padding: 12px 18px;
      border-radius: 30px;
      box-shadow: 0 4px 15px rgba(0,0,0,0.3);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      font-weight: bold;
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      transition: transform 0.2s ease, background 0.2s ease, opacity 0.2s ease;
      user-select: none;
    `;

    // Build DOM explicitly (no innerHTML for SVG — avoids CSP surprises).
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', '20');
    svg.setAttribute('height', '20');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    const els = [
      { tag: 'path', attrs: { d: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4' } },
      { tag: 'polyline', attrs: { points: '7 10 12 15 17 10' } },
      { tag: 'line', attrs: { x1: '12', y1: '15', x2: '12', y2: '3' } },
    ];
    for (const { tag, attrs } of els) {
      const el = document.createElementNS(svgNS, tag);
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
      svg.appendChild(el);
    }
    const label = document.createElement('span');
    label.textContent = T('toolbar_label');
    toolbar.appendChild(svg);
    toolbar.appendChild(label);

    // Optional badge showing last harvest count.
    const badge = document.createElement('span');
    badge.id = BADGE_ID;
    badge.style.cssText = `
      background: rgba(255, 255, 255, 0.25);
      color: #fff;
      font-size: 11px;
      font-weight: bold;
      padding: 2px 7px;
      border-radius: 10px;
      min-width: 18px;
      text-align: center;
      display: none;
    `;
    badge.textContent = '0';
    toolbar.appendChild(badge);

    toolbar.addEventListener('mouseenter', () => {
      if (!_busy) toolbar.style.transform = 'scale(1.05)';
    });
    toolbar.addEventListener('mouseleave', () => {
      toolbar.style.transform = 'scale(1)';
    });
    toolbar.addEventListener('click', () => {
      if (_busy) return;
      harvestAndDownloadImages();
    });

    document.body.appendChild(toolbar);
  }

  function setToolbarBusy(busy, labelKey) {
    _busy = busy;
    const t = document.getElementById(TOOLBAR_ID);
    if (!t) return;
    t.style.opacity = busy ? '0.75' : '1';
    t.style.cursor = busy ? 'wait' : 'pointer';
    t.style.pointerEvents = busy ? 'none' : 'auto';
    const span = t.querySelector('span:not(#' + BADGE_ID + ')');
    if (span) span.textContent = labelKey ? T(labelKey) : T('toolbar_label');
  }

  function setBadge(count) {
    _lastHarvestCount = count;
    const badge = document.getElementById(BADGE_ID);
    if (!badge) return;
    if (count > 0) {
      badge.textContent = count > 999 ? '999+' : String(count);
      badge.style.display = 'inline-block';
    } else {
      badge.style.display = 'none';
    }
  }

  // ===================== URL Conversion & Filtering =====================

  function getOriginalImageUrl(imgSrc) {
    if (!imgSrc || typeof imgSrc !== 'string') return null;
    if (!imgSrc.includes('pinimg.com')) return null;

    const isPinImage = /\/(?:originals|\d+x|rs\/\d+x\d+)\//.test(imgSrc);
    if (!isPinImage) return null;

    let url = imgSrc;
    url = url.replace(/\/\d+x\//, '/originals/');
    url = url.replace(/\/rs\/\d+x\d+\//, '/');
    return url;
  }

  /**
   * Extract a Pinterest Pin ID from a URL.
   * Pinterest image filenames are derived from a 32-hex-char hash.
   * Returns a short identifier (12 chars), or null if it can't be extracted.
   * Falls back to FNV-1a hash of the path tail for non-standard URLs.
   */
  function extractPinHash(url) {
    if (!url) return null;
    const m = /\/([a-f0-9]{16,32})\./i.exec(url);
    if (m) return m[1].slice(0, 12);
    try {
      const u = new URL(url);
      const parts = u.pathname.split('/').filter(Boolean);
      if (parts.length < 2) return null;
      const tail = parts.slice(-2).join('/');
      let h = 0x811c9dc5;
      for (let i = 0; i < tail.length; i++) {
        h ^= tail.charCodeAt(i);
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
      }
      return h.toString(16).padStart(8, '0').slice(0, 12);
    } catch {
      return null;
    }
  }

  // ===================== Auto-Scroll =====================

  /**
   * Count images that are actually pinimg pin images (not lazy stubs,
   * webapp icons, avatars, etc.).
   */
  function countHarvestableImages() {
    const images = document.querySelectorAll('img');
    let count = 0;
    for (const img of images) {
      const src = img.src || img.dataset.src;
      if (getOriginalImageUrl(src)) count++;
    }
    return count;
  }

  /**
   * Get a fingerprint of unique pin URLs currently in the DOM.
   * Used to detect when new pins load even if scrollHeight doesn't grow
   * (Pinterest's virtual scroll recycles DOM nodes).
   */
  function pinFingerprint() {
    const set = new Set();
    for (const img of document.querySelectorAll('img')) {
      const url = getOriginalImageUrl(img.src || img.dataset.src);
      if (url) set.add(url);
    }
    return Array.from(set).sort().join('|');
  }

  async function autoScrollForImages(onProgress) {
    const startTime = Date.now();
    let stableRounds = 0;
    let lastFingerprint = '';
    let lastHarvestable = 0;
    let totalUniquePinsSeen = 0;

    // Step 1: smooth scroll to bottom in increments. Pinterest uses
    // IntersectionObserver — each scroll event triggers lazy load of
    // pins entering the viewport.
    const stepSize = window.innerHeight * 0.8;
    let currentScroll = 0;
    let stableIterations = 0;

    for (let i = 0; i < SCROLL_MAX_ITERATIONS; i++) {
      const height = (document.scrollingElement || document.documentElement || document.body).scrollHeight;
      const harvestable = countHarvestableImages();
      const fp = pinFingerprint();
      const uniqueCount = fp ? fp.split('|').length : 0;

      if (uniqueCount > totalUniquePinsSeen) {
        totalUniquePinsSeen = uniqueCount;
      }
      onProgress(totalUniquePinsSeen);

      // Check stability — no new unique pins for several iterations
      if (fp === lastFingerprint && uniqueCount > 0) {
        stableRounds++;
      } else {
        stableRounds = 0;
        lastFingerprint = fp;
      }
      lastHarvestable = harvestable;

      // Exit conditions:
      // - We've scrolled past the page AND no new pins for STABLE rounds
      // - Wall-clock cap
      const atBottom = currentScroll >= height - window.innerHeight;
      if (atBottom && stableRounds >= SCROLL_STABLE_ROUNDS && i >= SCROLL_MIN_ROUNDS) break;
      if (Date.now() - startTime > SCROLL_MAX_DURATION_MS) break;

      // Smooth scroll: advance by stepSize, or jump to bottom if we're close
      if (currentScroll + stepSize < height) {
        currentScroll += stepSize;
      } else {
        currentScroll = height;
      }
      window.scrollTo(0, currentScroll);
      await sleep(SCROLL_PAUSE_MS);
    }

    // Step 2: scroll back to top so user sees the result
    window.scrollTo(0, 0);
    onProgress(totalUniquePinsSeen);
  }

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  // ===================== Settings =====================

  /**
   * Read user settings from chrome.storage.local. Falls back to defaults if
   * storage API is unavailable (e.g. when loaded outside the extension context).
   */
  async function loadSettings() {
    return new Promise((resolve) => {
      try {
        chrome.storage.local.get(['maxPins', 'folder', 'maxConcurrent'], (data) => {
          if (chrome.runtime.lastError) {
            resolve({ maxPins: 0, folder: 'Pinterest', maxConcurrent: 6 });
            return;
          }
          resolve({
            maxPins: typeof data.maxPins === 'number' && data.maxPins >= 0 ? data.maxPins : 0,
            folder: typeof data.folder === 'string' && data.folder ? data.folder : 'Pinterest',
            maxConcurrent: typeof data.maxConcurrent === 'number' ? data.maxConcurrent : 6,
          });
        });
      } catch {
        resolve({ maxPins: 0, folder: 'Pinterest', maxConcurrent: 6 });
      }
    });
  }

  // ===================== Harvest =====================

  async function harvestAndDownloadImages() {
    setToolbarBusy(true, 'status_loading');
    showToast(T('status_scroll_start'));

    try {
      // Merge triggerSettings (from popup click) with stored settings.
      const stored = await loadSettings();
      const settings = Object.assign({}, stored, _triggerSettings || {});
      _triggerSettings = null;

      const maxPins = settings.maxPins | 0;
      const folder = settings.folder || 'Pinterest';

      await autoScrollForImages(() => { /* could update badge mid-scroll */ });

      setToolbarBusy(true, 'status_collecting');
      const images = Array.from(document.querySelectorAll('img'));
      const validUrls = new Set();

      for (const img of images) {
        const src = img.src || img.dataset.src;
        const originalUrl = getOriginalImageUrl(src);
        if (originalUrl) validUrls.add(originalUrl);
      }

      let urlsArray = Array.from(validUrls).map((url, i) => ({
        url,
        index: i,
        pinHash: extractPinHash(url),
      }));

      // Apply maxPins limit (0 = unlimited).
      if (maxPins > 0 && urlsArray.length > maxPins) {
        urlsArray = urlsArray.slice(0, maxPins);
      }

      if (urlsArray.length === 0) {
        setBadge(0);
        showToast(T('status_no_images'), true);
        return;
      }

      setBadge(urlsArray.length);
      const foundLabel = maxPins > 0
        ? T('status_found_limited', urlsArray.length, maxPins)
        : T('status_found', urlsArray.length);
      showToast(foundLabel);

      chrome.runtime.sendMessage({
        action: 'downloadImages',
        urls: urlsArray,
        source: location.hostname,
        folder: folder,
        maxConcurrent: settings.maxConcurrent,
      }, (response) => {
        if (chrome.runtime.lastError) {
          console.warn('[PBD] sendMessage error:', chrome.runtime.lastError.message);
          showToast(T('status_comm_error'), true);
          return;
        }
        if (response && response.status === 'success') {
          showToast(T('status_done', response.count));
        } else {
          showToast(T('status_generic_error', (response && response.message) || 'unknown'), true);
        }
      });
    } catch (err) {
      console.error('[PBD] Harvest error:', err);
      showToast(T('status_generic_error', err.message), true);
    } finally {
      setToolbarBusy(false);
    }
  }

  // ===================== Toast =====================

  function showToast(message, isError = false) {
    const old = document.getElementById(TOAST_ID);
    if (old) old.remove();

    const toast = document.createElement('div');
    toast.id = TOAST_ID;
    toast.setAttribute('role', isError ? 'alert' : 'status');
    toast.style.cssText = `
      position: fixed;
      bottom: 80px;
      right: 20px;
      z-index: 1000000;
      background: ${isError ? '#b00020' : '#111'};
      color: #fff;
      padding: 10px 16px;
      border-radius: 8px;
      font-size: 13px;
      box-shadow: 0 4px 10px rgba(0,0,0,0.3);
      max-width: 320px;
      word-wrap: break-word;
      line-height: 1.4;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => { if (toast.parentNode) toast.remove(); }, 4000);
  }

  // ===================== Init & MutationObserver =====================

  let _scheduledReAdd = false;
  const observer = new MutationObserver(() => {
    if (_scheduledReAdd) return;
    if (!document.getElementById(TOOLBAR_ID)) {
      _scheduledReAdd = true;
      requestAnimationFrame(() => {
        _scheduledReAdd = false;
        if (!document.getElementById(TOOLBAR_ID)) createFloatingToolbar();
      });
    }
  });

  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, { childList: true, subtree: true });
    }, { once: true });
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    createFloatingToolbar();
  } else {
    window.addEventListener('load', createFloatingToolbar, { once: true });
  }

  // Listen for trigger events from the popup. The popup dispatches a
  // CustomEvent with the current settings (maxPins, folder, etc).
  window.addEventListener('pinterest-pro-trigger', (e) => {
    if (_busy) return;
    _triggerSettings = e.detail || null;
    harvestAndDownloadImages();
  });
})();
