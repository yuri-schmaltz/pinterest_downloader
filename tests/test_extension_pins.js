#!/usr/bin/env node
/**
 * Testes das funcoes de URL da extensao (extension/lib/pin_utils.js).
 *
 * A transformacao de URL e a parte mais critica da extensao: um erro aqui
 * significa que o usuario baixa a resolucao errada, ou baixa o avatar em
 * vez da imagem do pin. As funcoes moravam inline dentro do IIFE de
 * content.js, onde nenhum teste as alcancava -- por isso foram extraidas
 * para lib/pin_utils.js.
 *
 * Roda em Node puro, sem dependencias:
 *     node tests/test_extension_pins.js
 *
 * Exit code 0 = passou, 1 = falhou.
 */

'use strict';

const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const UTILS_PATH = path.join(ROOT, 'extension', 'lib', 'pin_utils.js');

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

// Carrega o arquivo como o navegador faria (script classico, sem export).
// O sandbox precisa de URL: um vm.createContext() vazio nao tem os globais
// do Node, e sem ele o fallback de extractPinHash (new URL(...)) cairia no
// catch e devolveria null -- testando um caminho que so quebra por causa
// do harness.
const sandbox = { window: {}, module: { exports: {} }, URL: URL, console: console };
vm.createContext(sandbox);
vm.runInContext(require('fs').readFileSync(UTILS_PATH, 'utf8'), sandbox);
const utils = sandbox.window.__pbdPinUtils;

console.log('='.repeat(64));
console.log('  Extensão -- funções de URL');
console.log('='.repeat(64));

checkTrue('as funções foram expostas em window.__pbdPinUtils', !!utils);
checkTrue('getOriginalImageUrl existe', typeof utils.getOriginalImageUrl === 'function');
checkTrue('extractPinHash existe', typeof utils.extractPinHash === 'function');
checkTrue('countHarvestableImages existe', typeof utils.countHarvestableImages === 'function');
checkTrue('pinFingerprint existe', typeof utils.pinFingerprint === 'function');

// ------------------------------------------------------------------
console.log('\n[1] getOriginalImageUrl -- resolução');
// ------------------------------------------------------------------
const original = 'https://i.pinimg.com/originals/ab/abcdef0123456789abcd.jpg';
const medium = 'https://i.pinimg.com/736x/ab/abcdef0123456789abcd.jpg';
const small = 'https://i.pinimg.com/236x/ab/abcdef0123456789abcd.jpg';

check('736x vira originals', utils.getOriginalImageUrl(medium), original);
check('236x vira originals', utils.getOriginalImageUrl(small), original);
check('originals fica como esta', utils.getOriginalImageUrl(original), original);

check(
  'rs/ quadrado vira a URL simples',
  utils.getOriginalImageUrl('https://i.pinimg.com/rs/736x736/ab/abcdef0123456789abcd.jpg'),
  'https://i.pinimg.com/ab/abcdef0123456789abcd.jpg'
);

// ------------------------------------------------------------------
console.log('\n[2] getOriginalImageUrl -- o que NÃO é pin');
// ------------------------------------------------------------------
check('avatar do Pinterest e ignorado', utils.getOriginalImageUrl('https://i.pinimg.com/user.jpg'), null);
check('icone do webapp e ignorado', utils.getOriginalImageUrl('https://s.pinimg.com/favicon.ico'), null);
check('host diferente e ignorado', utils.getOriginalImageUrl('https://example.com/originals/x.jpg'), null);
check('sem extensao pinimg e ignorado', utils.getOriginalImageUrl('https://i.pinimg.com/something'), null);
check('null devolve null', utils.getOriginalImageUrl(null), null);
check('string vazia devolve null', utils.getOriginalImageUrl(''), null);
check('numero devolve null', utils.getOriginalImageUrl(12345), null);
check('objeto devolve null', utils.getOriginalImageUrl({}), null);

// ------------------------------------------------------------------
console.log('\n[3] extractPinHash');
// ------------------------------------------------------------------
check(
  'extrai o hash do nome do arquivo',
  utils.extractPinHash(original),
  'abcdef012345'
);
check(
  'hash de 16 caracteres e aceito',
  utils.extractPinHash('https://i.pinimg.com/originals/ab/abcdef0123456789.jpg'),
  'abcdef012345'
);
check('url sem hash cai no fallback', typeof utils.extractPinHash('https://example.com/a/b'), 'string');
check('url invalida devolve null', utils.extractPinHash('nao-e-uma-url'), null);
check('null devolve null', utils.extractPinHash(null), null);
check('string vazia devolve null', utils.extractPinHash(''), null);
checkTrue(
  'o fallback e estavel (mesma entrada, mesmo hash)',
  utils.extractPinHash('https://example.com/a/b') === utils.extractPinHash('https://example.com/a/b')
);
checkTrue(
  'entradas diferentes dao hashes diferentes',
  utils.extractPinHash('https://example.com/a/b') !== utils.extractPinHash('https://example.com/a/c')
);

// ------------------------------------------------------------------
console.log('\n[4] contagem e fingerprint (com um DOM de mentira)');
// ------------------------------------------------------------------

function fakeDoc(images) {
  return {
    querySelectorAll: (sel) => {
      if (sel !== 'img') throw new Error(`seletor inesperado: ${sel}`);
      return images;
    },
  };
}

const doc = fakeDoc([
  { src: medium },
  { src: original },
  { src: 'https://i.pinimg.com/user.jpg' },
  { src: '' },
  { dataset: { src: small } },
  { src: 'https://example.com/outro.jpg' },
]);

check('conta so as imagens de pin', utils.countHarvestableImages(doc), 3);
check(
  'o fingerprint junta as duplicatas',
  utils.pinFingerprint(doc),
  [
    'https://i.pinimg.com/originals/ab/abcdef0123456789abcd.jpg',
    'https://i.pinimg.com/originals/ab/abcdef0123456789abcd.jpg',
  ]
    .filter((v, i, a) => a.indexOf(v) === i)
    .sort()
    .join('|')
);

check('doc sem imagens da zero', utils.countHarvestableImages(fakeDoc([])), 0);
check('fingerprint de doc vazio e vazio', utils.pinFingerprint(fakeDoc([])), '');

console.log('\n' + '='.repeat(64));
if (failures === 0) {
  console.log(`  ✅ ${checks} verificações, todas passaram`);
} else {
  console.log(`  ❌ ${failures} de ${checks} verificações falharam`);
}
console.log('='.repeat(64));

process.exit(failures === 0 ? 0 : 1);
