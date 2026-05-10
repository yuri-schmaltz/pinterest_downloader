/**
 * Content Script — injected into Pinterest pages.
 * Handles board discovery, pin collection, and image resolution.
 * Communicates with popup and service-worker via chrome.runtime messaging.
 */

(() => {
  "use strict";

  const U = window.__pbd_utils;
  if (!U) {
    console.error("[PBD] utils.js not loaded");
    return;
  }

  // ========== State ==========
  let _collecting = false;
  let _cancelled = false;

  // Metadata intercepted from XHR/Fetch responses
  const _interceptedMeta = {};

  // ========== XHR/Fetch Interception ==========

  /**
   * Intercept Pinterest API responses to grab image URLs directly.
   * This avoids needing to fetch each pin page individually.
   */
  function setupInterception() {
    // Intercept fetch responses
    const origFetch = window.fetch;
    window.fetch = async function (...args) {
      const response = await origFetch.apply(this, args);
      try {
        const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
        if (isPinterestApiUrl(url)) {
          const clone = response.clone();
          clone.json().then(data => extractPinMetadata(data)).catch(() => {});
        }
      } catch { /* ignore */ }
      return response;
    };

    // Intercept XMLHttpRequest
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this._pbdUrl = url;
      return origOpen.apply(this, [method, url, ...rest]);
    };

    XMLHttpRequest.prototype.send = function (...args) {
      if (this._pbdUrl && isPinterestApiUrl(this._pbdUrl)) {
        this.addEventListener("load", function () {
          try {
            const data = JSON.parse(this.responseText);
            extractPinMetadata(data);
          } catch { /* ignore */ }
        });
      }
      return origSend.apply(this, args);
    };
  }

  function isPinterestApiUrl(url) {
    return (
      url.includes("resource/BoardFeedResource/get") ||
      url.includes("resource/UserPinsResource/get") ||
      url.includes("resource/BoardResource/get") ||
      url.includes("/_/graphql/")
    );
  }

  function extractPinMetadata(data) {
    if (!data || typeof data !== "object") return;

    // REST API format
    if (data.resource_response) {
      const list = data.resource_response.data;
      if (Array.isArray(list)) {
        for (const pin of list) {
          extractSinglePin(pin);
        }
      }
    }

    // GraphQL format — recursive search
    findPinsRecursive(data);
  }

  function findPinsRecursive(obj) {
    if (!obj || typeof obj !== "object") return;
    if (Array.isArray(obj)) {
      for (const item of obj) findPinsRecursive(item);
      return;
    }

    const pid = String(obj.entityId || obj.id || "");
    const imagesDict = obj.images || {};
    const flatOrig = obj.images_orig || obj.images_736x || obj.images_474x;

    if (pid && (Object.keys(imagesDict).length || flatOrig)) {
      const pinUrl = `${U.PINTEREST_BASE_URL}/pin/${pid}/`;
      let imgUrl = null;

      if (flatOrig) {
        imgUrl = flatOrig.url;
      } else if (imagesDict.orig) {
        imgUrl = imagesDict.orig.url;
      } else if (imagesDict["736x"]) {
        imgUrl = imagesDict["736x"].url;
      }

      if (imgUrl) {
        _interceptedMeta[pinUrl] = {
          id: pid,
          url: pinUrl,
          imageUrl: imgUrl,
          title: obj.title || obj.gridTitle || obj.grid_title || "",
          description: obj.description || "",
        };
      }
    }

    for (const val of Object.values(obj)) {
      if (val && typeof val === "object") findPinsRecursive(val);
    }
  }

  function extractSinglePin(pin) {
    if (!pin || typeof pin !== "object") return;
    const pinId = String(pin.id || "");
    if (!pinId) return;

    const pinUrl = `${U.PINTEREST_BASE_URL}/pin/${pinId}/`;
    const images = pin.images || {};
    const orig = images.orig || images["736x"] || {};
    const imgUrl = orig.url;

    if (imgUrl) {
      _interceptedMeta[pinUrl] = {
        id: pinId,
        url: pinUrl,
        imageUrl: imgUrl,
        title: pin.title || pin.grid_title || "",
        description: pin.description || "",
      };
    }
  }

  // ========== Board Discovery ==========

  /**
   * Collect all boards from the current profile page.
   * Equivalent to collect_board_urls() in Python.
   */
  async function collectBoards() {
    _collecting = true;
    _cancelled = false;

    const bodyText = document.body.innerText || "";
    const isPrivate =
      bodyText.includes("This profile is private") ||
      bodyText.includes("Este perfil é privado") ||
      bodyText.includes("profile is private");

    if (isPrivate) {
      _collecting = false;
      return { error: "private", boards: [] };
    }

    // Determine username from URL
    const parts = location.pathname.split("/").filter(Boolean);
    const username = parts[0] || "";
    if (!username) {
      _collecting = false;
      return { error: "no_username", boards: [] };
    }

    const seenUrls = new Set();
    const results = [];
    let stableRounds = 0;
    let lastCount = 0;
    let lastHeight = 0;

    const maxIterations = 200;

    for (let i = 0; i < maxIterations; i++) {
      if (_cancelled) break;

      // Extract board cards from DOM
      const links = document.querySelectorAll("a[href]");
      for (const el of links) {
        const href = el.getAttribute("href");
        if (!href) continue;

        const hrefParts = href.split("/").filter(Boolean);
        if (
          hrefParts.length === 2 &&
          hrefParts[0].toLowerCase() === username.toLowerCase()
        ) {
          const boardSlug = hrefParts[1];
          if (U.EXCLUDED_BOARD_SLUGS.has(boardSlug.toLowerCase()) || boardSlug.startsWith("_")) {
            continue;
          }

          const fullUrl = `https://www.pinterest.com/${hrefParts[0]}/${hrefParts[1]}/`;
          if (seenUrls.has(fullUrl)) continue;
          seenUrls.add(fullUrl);

          // Extract metadata
          let title = boardSlug;
          let pinCount = "";
          let thumbUrl = "";

          try {
            const titleEl = el.querySelector('h2, [data-test-id="board-card-title"]');
            if (titleEl) {
              title = titleEl.innerText.trim();
            } else {
              const firstLine = el.innerText.split("\n")[0].trim();
              if (firstLine && !/^\d/.test(firstLine)) title = firstLine;
            }
          } catch { /* ignore */ }

          try {
            const text = el.innerText;
            const lines = text.split("\n").filter(l => l.trim());
            for (const line of lines) {
              const match = line.match(/^([\d,.]+\s*(?:mil|mi|k|m|pins|pin))\s*$/i);
              if (match) {
                pinCount = match[1].trim();
                break;
              }
            }
            if (!pinCount) {
              const match = text.match(/([\d,.]+\s*(?:mil|mi|k|m|pins|pin))\s*(?:Pins|Pin)?/i);
              if (match) pinCount = match[1].trim();
            }
          } catch { /* ignore */ }

          try {
            const img = el.querySelector("img");
            if (img) thumbUrl = img.getAttribute("src") || "";
          } catch { /* ignore */ }

          results.push({
            url: fullUrl,
            title: title.replace(/\n/g, " ").trim(),
            thumbnailUrl: thumbUrl,
            pinCount,
            pinCountInt: U.parsePinCount(pinCount),
          });
        }
      }

      // Scroll stability detection
      const currentHeight = document.scrollingElement
        ? document.scrollingElement.scrollHeight
        : document.body.scrollHeight;

      if (currentHeight === lastHeight && results.length === lastCount) {
        stableRounds++;
      } else {
        stableRounds = 0;
        lastHeight = currentHeight;
        lastCount = results.length;
      }

      if (stableRounds >= 15) break;

      // Scroll down
      const el = document.scrollingElement || document.documentElement || document.body;
      if (el) window.scrollTo(0, el.scrollHeight);

      await sleep(1200);
    }

    _collecting = false;
    return { error: null, boards: results };
  }

  // ========== Pin Collection ==========

  /**
   * Collect all pin URLs from the current board page.
   * Equivalent to _collect_pin_links_with_browser() in Python.
   */
  async function collectPins(options = {}) {
    _collecting = true;
    _cancelled = false;

    const maxPins = options.maxPins || null;
    const scrollPause = options.scrollPause || 1.2;

    const seen = new Set();
    let stableRounds = 0;
    let lastCount = 0;
    let lastHeight = 0;

    // Wait for initial pins to load
    await sleep(2000);

    const maxIterations = 500;

    for (let i = 0; i < maxIterations; i++) {
      if (_cancelled) break;

      // Close popups periodically
      if (stableRounds > 2) {
        try {
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
          const closes = document.querySelectorAll('[aria-label="Close"], [aria-label="Fechar"]');
          closes.forEach(c => {
            if (c.innerText === "✕" || c.innerText === "X") c.click();
          });
        } catch { /* ignore */ }
      }

      // Collect pin links
      const pinLinks = document.querySelectorAll('a[href^="/pin/"]');
      for (const a of pinLinks) {
        const href = a.getAttribute("href");
        if (!href) continue;
        let u = U.absUrl(href.split("?")[0]);
        u = u.replace("://br.pinterest.com/", "://www.pinterest.com/");
        if (u.startsWith(`${U.PINTEREST_BASE_URL}/pin/`)) {
          seen.add(u);
        }
      }

      if (maxPins && seen.size >= maxPins) break;

      // Scroll stability detection
      const currentHeight = document.scrollingElement
        ? document.scrollingElement.scrollHeight
        : document.body.scrollHeight;

      const bodyText = document.body.innerText || "";
      const hasMoreLikeThis =
        bodyText.includes("Mais como esse") || bodyText.includes("More like this");

      const isBottom = (window.innerHeight + window.scrollY) >= (document.body.offsetHeight - 800);

      if (seen.size === lastCount) {
        if (hasMoreLikeThis && isBottom) {
          stableRounds += 2;
        } else if (currentHeight === lastHeight) {
          stableRounds += 1;
        } else {
          stableRounds += 0.5;
        }
      } else {
        stableRounds = 0;
        lastHeight = currentHeight;
        lastCount = seen.size;
      }

      if (stableRounds >= 20) break;

      // Scroll
      const el = document.scrollingElement || document.documentElement || document.body;
      if (el) window.scrollTo(0, el.scrollHeight);

      // Extra wait when stuck
      if (stableRounds > 5) {
        await sleep(1000);
      } else {
        await sleep(500);
      }

      await sleep(scrollPause * 1000);

      // Report progress
      chrome.runtime.sendMessage({
        type: "PIN_COLLECT_PROGRESS",
        count: seen.size,
        stable: stableRounds,
      }).catch(() => {});
    }

    const pinUrls = maxPins ? [...seen].slice(0, maxPins) : [...seen];

    _collecting = false;
    return {
      pins: pinUrls,
      intercepted: { ..._interceptedMeta },
      total: pinUrls.length,
    };
  }

  // ========== Image Resolution ==========

  /**
   * Resolve a single pin URL to its full-size image URL.
   * Uses intercepted metadata first, then falls back to fetching the pin page.
   */
  async function resolvePin(pinUrl) {
    // Check intercepted metadata first
    if (_interceptedMeta[pinUrl]) {
      return _interceptedMeta[pinUrl].imageUrl;
    }

    // Fallback: fetch the pin page and extract og:image
    try {
      const resp = await fetch(pinUrl, { credentials: "include" });
      if (!resp.ok) return null;
      const html = await resp.text();

      // Try video first
      let match = html.match(/<meta[^>]+property=["']og:video:secure_url["'][^>]+content=["']([^"']+)/i);
      if (!match) {
        match = html.match(/<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:video:secure_url["']/i);
      }

      // Fallback to image
      if (!match) {
        match = html.match(/<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)/i);
      }
      if (!match) {
        match = html.match(/<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']/i);
      }

      if (match) {
        return match[1].split("?")[0];
      }
    } catch { /* ignore */ }
    return null;
  }

  /**
   * Resolve multiple pins in parallel batches.
   */
  async function resolvePins(pinUrls, interceptedData = {}) {
    // Merge intercepted data
    Object.assign(_interceptedMeta, interceptedData);

    const results = {};
    const toFetch = [];

    // Check intercepted first
    for (const url of pinUrls) {
      if (_interceptedMeta[url]) {
        results[url] = _interceptedMeta[url].imageUrl;
      } else {
        toFetch.push(url);
      }
    }

    // Fetch remaining in batches of 6
    const batchSize = 6;
    for (let i = 0; i < toFetch.length; i += batchSize) {
      if (_cancelled) break;
      const batch = toFetch.slice(i, i + batchSize);
      const promises = batch.map(async (url) => {
        const img = await resolvePin(url);
        if (img) results[url] = img;
      });
      await Promise.all(promises);

      // Report progress
      chrome.runtime.sendMessage({
        type: "RESOLVE_PROGRESS",
        resolved: Object.keys(results).length,
        total: pinUrls.length,
      }).catch(() => {});
    }

    return results;
  }

  // ========== Message Handler ==========

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    switch (msg.type) {
      case "GET_PAGE_INFO": {
        const pageType = U.detectPageType(location.href);
        const parts = location.pathname.split("/").filter(Boolean);
        sendResponse({
          url: location.href,
          pageType,
          username: parts[0] || "",
          boardName: parts.length >= 2 ? parts[1] : "",
          isPinterest: location.hostname.includes("pinterest"),
        });
        return false;
      }

      case "COLLECT_BOARDS": {
        collectBoards().then(result => sendResponse(result));
        return true; // async
      }

      case "COLLECT_PINS": {
        collectPins(msg.options || {}).then(result => sendResponse(result));
        return true;
      }

      case "RESOLVE_PINS": {
        resolvePins(msg.pins, msg.intercepted || {}).then(result => sendResponse(result));
        return true;
      }

      case "CANCEL": {
        _cancelled = true;
        sendResponse({ ok: true });
        return false;
      }

      case "PING": {
        sendResponse({ ok: true, collecting: _collecting });
        return false;
      }

      default:
        sendResponse({ error: "unknown_message" });
        return false;
    }
  });

  // ========== Init ==========
  setupInterception();

  // Helpers
  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  console.log("[PBD] Pinterest Board Downloader content script loaded.");
})();
