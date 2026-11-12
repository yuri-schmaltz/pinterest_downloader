#!/usr/bin/env node
/**
 * Testes do i18n da extensão (extension/lib/i18n.js).
 *
 * A extensão não tinha nenhum teste. Este arquivo cobre o ponto mais
 * frágil dela: a camada de tradução, que tem dois caminhos de execução --
 * com chrome.i18n (navegador real) e sem ele (fallback em português).
 *
 * Roda em Node puro, sem dependências:
 *     node tests/test_extension_i18n.js
 *
 * Exit code 0 = passou, 1 = falhou.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const I18N_PATH = path.join(ROOT, 'extension', 'lib', 'i18n.js');
const MESSAGES_PATH = path.join(ROOT, 'extension', '_locales', 'pt_BR', 'messages.json');

let failures = 0;
let checks = 0;

function check(label, got, expected) {
  checks++;
  if (got === expected) {
    console.log(`  OK   ${label}: ${JSON.stringify(got)}`);
  } else {
    failures++;
    console.log(`  FAIL ${label}: ${JSON.stringify(got)} (esperado ${JSON.stringify(expected)})`);
  }
}

function checkTrue(label, condition, detail) {
  checks++;
  if (condition) {
    console.log(`  OK   ${label}`);
  } else {
    failures++;
    console.log(`  FAIL ${label}${detail ? ` -- ${detail}` : ''}`);
  }
}

const i18nSource = fs.readFileSync(I18N_PATH, 'utf8');
const messages = JSON.parse(fs.readFileSync(MESSAGES_PATH, 'utf8'));

/** Carrega o i18n.js como o navegador faria: script clássico, sem export. */
function loadI18n(chromeMock) {
  const sandbox = {
    window: {},
    navigator: { language: 'pt-BR' },
  };
  if (chromeMock) sandbox.chrome = chromeMock;
  vm.createContext(sandbox);
  vm.runInContext(i18nSource, sandbox);
  return sandbox.window.__pbdI18n;
}

/**
 * Reproduz o que o Chrome faz: as mensagens declaram placeholders NOMEADOS
 * ($COUNT$) mapeados para substituições posicionais ($1, $2).
 */
function chromeI18nMock() {
  return {
    i18n: {
      getUILanguage: () => 'pt-BR',
      getMessage(name, subs) {
        const entry = messages[name];
        if (!entry) return '';
        let out = entry.message;
        for (const [placeholderName, definition] of Object.entries(entry.placeholders || {})) {
          const index = parseInt(String(definition.content).replace('$', ''), 10) - 1;
          if (index >= 0 && subs && subs[index] !== undefined) {
            out = out.replace(new RegExp(`\\$${placeholderName}\\$`, 'gi'), String(subs[index]));
          }
        }
        return out;
      },
    },
    runtime: { getManifest: () => ({ version: '2.0.3' }) },
  };
}

console.log('='.repeat(64));
console.log('  Extensão -- i18n');
console.log('='.repeat(64));

// ------------------------------------------------------------------
console.log('\n[1] Fallback (sem chrome.i18n)');
// ------------------------------------------------------------------
const fallback = loadI18n(null);

check('status_found', fallback.t('status_found', 47), '47 imagens encontradas. Iniciando downloads…');
check(
  'status_found_limited',
  fallback.t('status_found_limited', 47, 100),
  'Limitado a 47 de 100 pins. Iniciando downloads…'
);
check('status_done', fallback.t('status_done', 12), '✓ 12 downloads iniciados!');
check('status_generic_error', fallback.t('status_generic_error', 'Erro de rede'), 'Erro: Erro de rede');
check('folder_selected', fallback.t('folder_selected', 'MeusQuadros'), 'Pasta definida: MeusQuadros');
check('folder_pick_failed', fallback.t('folder_pick_failed', 'sem permissão'), 'Falha ao selecionar pasta: sem permissão');
check('status_saved', fallback.t('status_saved', ''), 'Configurações salvas');
check('status_triggering', fallback.t('status_triggering'), 'Iniciando download…');
check('status_triggered', fallback.t('status_triggered'), '✓ Iniciado! Acompanhe o botão na página para ver o progresso.');
check('status_no_tab', fallback.t('status_no_tab'), 'Nenhuma aba ativa.');
check('status_wrong_site', fallback.t('status_wrong_site'), 'Navegue para uma página do Pinterest primeiro.');
check('opt_folder', fallback.t('opt_folder'), 'Pasta de destino');
check('opt_concurrent', fallback.t('opt_concurrent'), 'Downloads paralelos');
check('status_no_images', fallback.t('status_no_images'), 'Nenhuma imagem do Pinterest encontrada.');
check('popup_footer', fallback.t('popup_footer', '2.0.3'), 'Versão Pro 2.0.3');
check('getLocale (fallback)', fallback.getLocale(), 'pt_BR');
check('getVersion (fallback)', fallback.getVersion(), '2.0.3');

// Toda chave de _locales precisa existir no dicionário de fallback,
// senão o usuário vê o nome cru da chave ("status_triggering").
const missing = Object.keys(messages).filter((key) => fallback.t(key, 1, 2) === key);
checkTrue(
  'toda chave de _locales tem entrada no fallback',
  missing.length === 0,
  missing.length ? `sem fallback: ${missing.join(', ')}` : ''
);

// ------------------------------------------------------------------
console.log('\n[2] Caminho real (com chrome.i18n)');
// ------------------------------------------------------------------
const real = loadI18n(chromeI18nMock());

check('status_found', real.t('status_found', 47), '47 imagens encontradas. Iniciando downloads…');
check(
  'status_found_limited',
  real.t('status_found_limited', 47, 100),
  'Limitado a 47 de 100 pins. Iniciando downloads…'
);
check('status_done', real.t('status_done', 12), '✓ 12 downloads iniciados!');
check('status_generic_error', real.t('status_generic_error', 'Erro de rede'), 'Erro: Erro de rede');
check('folder_selected', real.t('folder_selected', 'MeusQuadros'), 'Pasta definida: MeusQuadros');
check('popup_footer', real.t('popup_footer', real.getVersion()), 'Versão Pro 2.0.3');
check('getLocale', real.getLocale(), 'pt-BR');
check('getVersion (do manifest)', real.getVersion(), '2.0.3');

// ------------------------------------------------------------------
console.log('\n[3] Cobertura dos placeholders');
// ------------------------------------------------------------------
// Toda mensagem com placeholder precisa resolver para algo que nao
// contenha mais "$" -- nem no caminho real, nem no fallback.
for (const [key, entry] of Object.entries(messages)) {
  const placeholders = Object.keys(entry.placeholders || {});
  if (placeholders.length === 0) continue;

  const args = placeholders.map((_, i) => `V${i + 1}`);
  for (const [label, api] of [['real', real], ['fallback', fallback]]) {
    const rendered = api.t(key, ...args);
    checkTrue(
      `${label}: ${key} substitui todos os placeholders`,
      !/\$[A-Z_]+\$/.test(rendered),
      `resultado ainda tem placeholder: ${JSON.stringify(rendered)}`
    );
  }
}

console.log('\n' + '='.repeat(64));
if (failures === 0) {
  console.log(`  ✅ ${checks} verificações, todas passaram`);
} else {
  console.log(`  ❌ ${failures} de ${checks} verificações falharam`);
}
console.log('='.repeat(64));

process.exit(failures === 0 ? 0 : 1);
