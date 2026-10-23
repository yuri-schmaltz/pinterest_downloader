// Shared helpers for working with Pinterest image URLs.
//
// Loaded BEFORE content.js via the manifest's content_scripts array, and
// exposed on window.__pbdPinUtils so it can be unit tested outside the
// browser (see tests/test_extension_pins.js).
//
// These used to live inline in content.js, which made them untestable: the
// whole file is an IIFE, so nothing was reachable from a test. The URL
// transformation is the part of the extension most worth testing -- a bug
// here means the user downloads the wrong resolution.

(function () {
  'use strict';

  /**
   * Return the highest-resolution URL for a Pinterest image, or null if the
   * source is not a pin image at all.
   *
   * Pinterest serves several sizes of the same image:
   *   /736x/abc.jpg      -> medium
   *   /originals/abc.jpg -> original
   *   /rs/736x736/abc.jpg -> resized square
   *
   * Anything that is not a pinimg image (avatars, webapp icons, lazy-load
   * stubs) returns null so it is never harvested.
   */
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
   *
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

  /**
   * Count images that are actually pinimg pin images (not lazy stubs,
   * webapp icons, avatars, etc.).
   */
  function countHarvestableImages(doc) {
    const d = doc || (typeof document !== 'undefined' ? document : null);
    if (!d) return 0;
    const images = d.querySelectorAll('img');
    let count = 0;
    for (const img of images) {
      const src = img.src || (img.dataset && img.dataset.src);
      if (getOriginalImageUrl(src)) count++;
    }
    return count;
  }

  /**
   * Get a fingerprint of unique pin URLs currently in the DOM.
   * Used to detect when new pins load even if scrollHeight doesn't grow
   * (Pinterest's virtual scroll recycles DOM nodes).
   */
  function pinFingerprint(doc) {
    const d = doc || (typeof document !== 'undefined' ? document : null);
    if (!d) return '';
    const set = new Set();
    for (const img of d.querySelectorAll('img')) {
      const url = getOriginalImageUrl(img.src || (img.dataset && img.dataset.src));
      if (url) set.add(url);
    }
    return Array.from(set).sort().join('|');
  }

  const api = { getOriginalImageUrl, extractPinHash, countHarvestableImages, pinFingerprint };
  if (typeof window !== 'undefined') window.__pbdPinUtils = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
