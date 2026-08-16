(function () {
  'use strict';

  // ===================== Floating Toolbar =====================

  function createFloatingToolbar() {
    if (document.getElementById('pinterest-pro-toolbar')) return;

    const toolbar = document.createElement('div');
    toolbar.id = 'pinterest-pro-toolbar';
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
      gap: 10px;
      cursor: pointer;
      transition: transform 0.2s ease, background 0.2s ease;
    `;

    toolbar.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
      <span>Baixar Imagens da Página</span>
    `;

    toolbar.addEventListener('mouseenter', () => toolbar.style.transform = 'scale(1.05)');
    toolbar.addEventListener('mouseleave', () => toolbar.style.transform = 'scale(1)');
    toolbar.addEventListener('click', harvestAndDownloadImages);

    document.body.appendChild(toolbar);
  }

  // ===================== URL Conversion & Filtering =====================

  /**
   * Convert a Pinterest thumbnail URL to its highest-resolution /originals/ variant.
   * Returns null if the URL is not a Pinterest pin image (e.g. webapp UI assets).
   *
   * Validates that the URL looks like an actual pin image — matches one of:
   *   /<size>x/path  (236x, 474x, 564x, 736x, ...)
   *   /originals/path
   *   /rs/<WxH>/path
   *
   * Rejects UI assets like /webapp/, /images/, /logos/ even though they're on
   * s.pinimg.com / i.pinimg.com.
   */
  function getOriginalImageUrl(imgSrc) {
    if (!imgSrc || typeof imgSrc !== 'string') return null;
    if (!imgSrc.includes('pinimg.com')) return null;

    // Require the URL to look like a pin image path (numeric size, originals, or rs/<dim>).
    const isPinImage = /\/(?:originals|\d+x|rs\/\d+x\d+)\//.test(imgSrc);
    if (!isPinImage) return null;

    let url = imgSrc;
    // Rewrite any size variant (236x, 474x, 564x, 736x, 1200x, ...) to /originals/.
    // Also normalizes regional subdomains like i1-e.pinimg.com → keep them intact.
    url = url.replace(/\/\d+x\//, '/originals/');
    url = url.replace(/\/rs\/\d+x\d+\//, '/');
    return url;
  }

  // ===================== Harvest =====================

  function harvestAndDownloadImages() {
    const images = Array.from(document.querySelectorAll('img'));
    const validUrls = new Set();

    for (const img of images) {
      const src = img.src || img.dataset.src;
      const originalUrl = getOriginalImageUrl(src);
      if (originalUrl) validUrls.add(originalUrl);
    }

    const urlsArray = Array.from(validUrls).map(url => ({ url }));

    if (urlsArray.length === 0) {
      showToast('Nenhuma imagem do Pinterest encontrada.', true);
      return;
    }

    chrome.runtime.sendMessage({
      action: "downloadImages",
      urls: urlsArray
    }, response => {
      if (chrome.runtime.lastError) {
        console.warn('[PBD] sendMessage error:', chrome.runtime.lastError.message);
        showToast('Erro ao comunicar com a extensão.', true);
        return;
      }
      if (response && response.status === "success") {
        showToast(`Iniciando download de ${response.count} imagens!`);
      } else {
        showToast('Erro ao iniciar os downloads.', true);
      }
    });
  }

  // ===================== Toast =====================

  function showToast(message, isError = false) {
    const toast = document.createElement('div');
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
    `;
    toast.innerText = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }

  // ===================== Init & MutationObserver =====================

  const observer = new MutationObserver(() => {
    if (!document.getElementById('pinterest-pro-toolbar')) {
      createFloatingToolbar();
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  if (document.readyState === 'complete') {
    createFloatingToolbar();
  } else {
    window.addEventListener('load', createFloatingToolbar);
  }
})();
