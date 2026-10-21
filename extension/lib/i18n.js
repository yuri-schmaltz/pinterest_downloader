// Shared i18n helper. Loaded as a classic script BEFORE content.js / popup.js
// via content_scripts order and a <script> tag in popup.html.
//
// Exposes window.__pbdI18n with:
//   t(key, ...args)  → translated string with $1, $2 placeholders replaced
//   getLocale()      → current locale (e.g. 'pt_BR', 'en', 'es')
//
// If chrome.i18n is unavailable (e.g. running as injected test code), falls
// back to a simple Portuguese dictionary so the extension still works.

(function () {
  'use strict';

  // Built-in fallback strings (Portuguese) used when chrome.i18n is missing
  // (e.g. when content.js is loaded outside the extension context for tests).
  const FALLBACK = {
    toolbar_label: 'Baixar Imagens da Página',
    toolbar_aria: 'Baixar imagens do Pinterest',
    toolbar_title: 'Clique para baixar todas as imagens visíveis (a página rola automaticamente)',
    popup_title: 'Pinterest Downloader',
    popup_button: 'Baixar Imagens Visíveis',
    popup_footer: 'Versão Pro 2.0.0',
    status_loading: 'Carregando página…',
    status_collecting: 'Coletando imagens…',
    status_no_images: 'Nenhuma imagem do Pinterest encontrada.',
    status_scroll_start: 'Rolando para carregar todas as imagens…',
    status_done_prefix: '✓ ',
    status_comm_error: 'Erro ao comunicar com a extensão.',
    status_generic_error_prefix: 'Erro: ',
    opt_max_pins: 'Quantidade máxima de pins',
    opt_max_pins_hint: '0 = sem limite (baixa todos)',
    status_found_limited: 'Limitado a $1$ de $2$ pins. Iniciando downloads…',
    pick_folder_title: 'Escolher pasta de destino',
    folder_selected: 'Pasta definida: $1$',
    folder_pick_failed: 'Falha ao selecionar pasta: $1$',
    folder_pick_fallback: 'Digite o nome da pasta manualmente.',
  };

  function getLocale() {
    try {
      if (typeof chrome !== 'undefined' && chrome.i18n && chrome.i18n.getUILanguage) {
        return chrome.i18n.getUILanguage();
      }
    } catch { /* ignore */ }
    return (navigator.language || 'en').replace('-', '_');
  }

  function replacePlaceholders(message, args) {
    if (!args || args.length === 0) return message;
    return message.replace(/\$(\d+)\$/g, (m, n) => {
      const idx = parseInt(n, 10) - 1;
      return (idx >= 0 && idx < args.length) ? String(args[idx]) : m;
    });
  }

  function t(key, ...args) {
    // Prefer chrome.i18n when available.
    try {
      if (typeof chrome !== 'undefined' && chrome.i18n && chrome.i18n.getMessage) {
        const msg = chrome.i18n.getMessage(key, args);
        if (msg) return msg;
      }
    } catch { /* fall through */ }
    // Fallback: build a reasonable string from FALLBACK.
    let fallback = FALLBACK[key];
    if (fallback === undefined) return key;
    // Handle special suffix-style keys for parameterized strings.
    if (args.length > 0) {
      if (key === 'status_found') fallback = '$COUNT$ imagens encontradas. Iniciando downloads…';
      else if (key === 'status_done') fallback = '✓ $COUNT$ downloads iniciados!';
      else if (key === 'status_generic_error') fallback = 'Erro: $MESSAGE$';
      else if (key === 'popup_footer') fallback = 'Versão Pro $VERSION$';
      return replacePlaceholders(fallback, args);
    }
    return fallback;
  }

  window.__pbdI18n = { t, getLocale };
})();
