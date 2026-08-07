/**
 * Shared utilities for the Pinterest Board Downloader extension.
 *
 * Loaded before content.js and popup.js via the manifest's
 * `content_scripts[0].js` array (and re-injected on demand by
 * popup.js's ensureContentScript). The content script exposes
 * the API on `window.__pbd_utils` for cross-context reuse.
 *
 * This file is the browser-side mirror of the equivalent helpers
 * in `src/pinterest_board_dl.py` (PINTEREST_BASE_URL, parse_pin_count,
 * _abs_url). Keep them in sync when Pinterest changes layout.
 */

(() => {
  "use strict";

  // ========== Constants ==========

  const PINTEREST_BASE_URL = "https://www.pinterest.com";

  // Slugs that are navigation tabs on a profile page, not real boards.
  // Mirrors the `exclude = {...}` set in pinterest_board_dl.collect_board_urls.
  const EXCLUDED_BOARD_SLUGS = new Set([
    "boards",
    "pins",
    "created",
    "tried",
    "_created",
    "_saved",
    "ideas",
    "more-ideas",
    "following",
    "followers",
  ]);

  // ========== URL helpers ==========

  /**
   * Convert a possibly-relative href to an absolute Pinterest URL
   * (query string stripped).
   */
  function absUrl(href) {
    if (!href) return "";
    const noQuery = href.split("?")[0];
    if (noQuery.startsWith("http")) return noQuery;
    if (noQuery.startsWith("/")) return (PINTEREST_BASE_URL + noQuery).split("?")[0];
    return noQuery;
  }

  /**
   * Detect the type of Pinterest page we're on, from the location URL.
   * Returns one of: "profile" | "board" | "pin" | "search" | "unknown".
   */
  function detectPageType(href) {
    try {
      const u = new URL(href);
      if (!u.hostname.includes("pinterest")) return "unknown";
      const parts = u.pathname.split("/").filter(Boolean);
      if (parts.length === 0) return "unknown";
      // /pin/<id>/
      if (parts[0] === "pin" && parts[1]) return "pin";
      // /search/pins/?q=...
      if (parts[0] === "search") return "search";
      // /<user>/<board>/  -> board
      // /<user>/          -> profile
      if (parts.length >= 2) return "board";
      return "profile";
    } catch {
      return "unknown";
    }
  }

  // ========== Pin count parser ==========

  /**
   * Parse a Pinterest pin count string ("1,2 mil", "1.2k", "10 pins", "1.5M")
   * into an integer. Mirrors parse_pin_count() in pinterest_board_dl.py.
   * Returns null on unparseable input.
   */
  function parsePinCount(countStr) {
    if (!countStr) return null;
    let s = String(countStr).trim().toLowerCase();
    s = s.replace(/,/g, "").replace(/pins?/g, "").trim();
    if (!s) return null;

    let multiplier = 1;
    if (/mil|k\b/.test(s)) {
      multiplier = 1000;
      s = s.replace(/mil|k/g, "").trim();
    } else if (/\bmi\b|m\b/.test(s) && !/^m(il)?$/.test(s) === false) {
      // 'mi' or 'm' as a thousands/millions suffix
      multiplier = 1000000;
      s = s.replace(/\bmi\b|m/g, "").trim();
    }

    // Last-resort: convert comma-decimal
    s = s.replace(",", ".");
    const n = parseFloat(s);
    if (isNaN(n)) return null;
    return Math.round(n * multiplier);
  }

  // ========== Export ==========

  const api = {
    PINTEREST_BASE_URL,
    EXCLUDED_BOARD_SLUGS,
    absUrl,
    detectPageType,
    parsePinCount,
  };

  // Content script reads it off window; popup/service-worker can also use it
  // if the file is loaded (it currently isn't in the popup, by design — the
  // popup talks to the content script via chrome.runtime.sendMessage).
  if (typeof window !== "undefined") {
    window.__pbd_utils = api;
  }

  // CommonJS export for any non-browser context (tests, future node usage)
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})();
