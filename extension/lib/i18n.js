// Shared i18n helper. Loaded as a classic script BEFORE content.js / popup.js
// via content_scripts order and a <script> tag in popup.html.
//
// Exposes window.__pbdI18n with:
//   t(key, ...args)  -> translated string with $1, $2 placeholders replaced
//   getLocale()      -> current locale (e.g. 'pt_BR', 'en', 'es')
//   getVersion()     -> extension version, read from the manifest
//
// If chrome.i18n is unavailable (e.g. running as injected test code), falls
// back to a simple Portuguese dictionary so the extension still works.
//
// PLACEHOLDER CONVENTION
// The _locales/*/messages.json files declare named placeholders that resolve
// to positional substitutions, e.g.
//   "status_found": {
//     "message": "$COUNT$ imagens encontradas. Initiando downloads...",
//     "placeholders": { "count": { "content": "$1" } }
//   }
// so chrome.i18n.getMessage('status_found', [42]) substitutes correctly.
//
// The fallback below has to mirror that: it must use POSITIONAL $1$/$2$
// placeholders, not the named ones. The named form would be left literal
// by replacePlaceholders().

(function () {
  'use strict';

  // Built-in fallback strings (Portuguese) used when chrome.i18n is missing
  // (e.g. when content.js is loaded outside the extension context for tests).
  // Every key that exists in _locales/pt_BR/messages.json must be present
  // here -- otherwise t() returns the raw key and the user sees
  // "status_triggering" instead of a message.
  const FALLBACK = {
    extension_name: 'Pinterest Pro Downloader',
    extension_description: 'Extensão avançada para download de imagens em alta resolução do Pinterest.',
    toolbar_label: 'Baixar Imagens da Página',
    toolbar_aria: 'Baixar imagens do Pinterest',
    toolbar_title: 'Clique para baixar todas as imagens visíveis (a página rola automaticamente)',
    popup_title: 'Pinterest Downloader',
    popup_button: 'Baixar Imagens Visíveis',
    popup_footer: 'Versão Pro $1$',
    opt_folder: 'Pasta de destino',
    opt_concurrent: 'Downloads paralelos',
    opt_max_pins: 'Quantidade máxima de pins',
    opt_max_pins_hint: '0 = sem limite (baixa todos)',
    status_saved: 'Configurações salvas',
    status_no_tab: 'Nenhuma aba ativa.',
    status_wrong_site: 'Navegue para uma página do Pinterest primeiro.',
    status_triggering: 'Iniciando download…',
    status_triggered: '✓ Iniciado! Acompanhe o botão na página para ver o progresso.',
    status_loading: 'Carregando página…',
    status_collecting: 'Coletando imagens…',
    status_no_images: 'Nenhuma imagem do Pinterest encontrada.',
    status_scroll_start: 'Rolando para carregar todas as imagens…',
    status_found: '$1$ imagens encontradas. Iniciando downloads…',
    status_found_limited: 'Limitado a $1$ de $2$ pins. Iniciando downloads…',
    status_done: '✓ $1$ downloads iniciados!',
    status_comm_error: 'Erro ao comunicar com a extensão.',
    status_generic_error: 'Erro: $1$',
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

  // Resolve a versão a partir do manifest, para não haver uma quarta
  // fonte de verdade além de manifest.json e pyproject.toml.
  function getVersion() {
    try {
      if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.getManifest) {
        const v = chrome.runtime.getManifest().version;
        if (v) return v;
      }
    } catch { /* ignore */ }
    return '2.0.3';
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

    return replacePlaceholders(fallback, args);
  }

  window.__pbdI18n = { t, getLocale, getVersion };
})();
