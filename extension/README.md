# Pinterest Pro Downloader

Extensão para navegador que baixa imagens do Pinterest em alta resolução (`/originals/`) com um único clique. Internacionalizada em **pt-BR, en, es**.

## Funcionalidades

- ✅ **Qualidade máxima** — converte thumbnails (`236x`, `474x`, `564x`, `736x`, `1200x`, etc.) para a versão `originals`
- ✅ **Auto-scroll** — rola a página inteira antes de baixar, capturando imagens carregadas via infinite scroll
- ✅ **Lazy-load** — captura imagens que ainda não terminaram de carregar (via `data-src`)
- ✅ **Fila com limite configurável** (1–12 paralelos, padrão 6) — sem sobrecarregar o browser
- ✅ **Filenames descritivos** — usa o pin ID do Pinterest, com fallback FNV-1a hash para URLs não-padrão
- ✅ **Pasta de destino configurável** — salva em qualquer subpasta de `Downloads/`
- ✅ **Dedup** — múltiplos cliques não baixam a mesma imagem duas vezes (memoizado por pinHash)
- ✅ **i18n** — 3 idiomas com fallback automático: pt-BR (default), en, es
- ✅ **Badge counter** — mostra quantos downloads foram iniciados no ícone da extensão
- ✅ **Cross-browser** — Chrome/Brave/Edge (MV3 service worker) e Firefox 121+ (background event page)

## Instalação

### Chrome / Brave / Edge (Chromium)

1. Abra `chrome://extensions/`
2. Ative o **Modo do desenvolvedor** (canto superior direito)
3. Clique em **Carregar sem compactação**
4. Selecione a pasta `extension/`

### Firefox 121+

1. Abra `about:debugging#/runtime/this-firefox`
2. Clique em **Carregar extensão temporária...**
3. Selecione o arquivo `manifest.json` da pasta `extension/`

## Uso

### Pelo botão flutuante
1. Navegue para qualquer página do Pinterest (home, board, perfil, busca, pin individual)
2. Clique no botão flutuante **"Baixar Imagens da Página"** no canto inferior direito
3. Aguarde o scroll automático terminar (até 60s para boards grandes)
4. Os arquivos serão salvos em `Downloads/Pinterest/<host>/<pin-id>.<ext>`

### Pelo popup
1. Clique no ícone da extensão na barra do navegador
2. (Opcional) ajuste **Pasta de destino** e **Downloads paralelos**
3. Clique em **Baixar Imagens Visíveis**

## Configuração

As configurações são salvas via `chrome.storage.local`:

| Chave | Tipo | Padrão | Descrição |
|---|---|---|---|
| `folder` | string | `"Pinterest"` | Subpasta dentro de `Downloads/` |
| `maxConcurrent` | number | `6` | Downloads simultâneos (1–12) |

## Arquitetura

```
extension/
├── manifest.json            — Manifest V3 com i18n + storage + action badge
├── background.js            — SW + fila com MAX_CONCURRENT + dedup + storage + badge
├── content.js               — Toolbar i18n + auto-scroll + harvest + URL conversion
├── popup.html               — UI de configuração + trigger
├── popup.js                 — Storage + chrome.scripting + i18n
├── lib/
│   └── i18n.js              — Polyfill de chrome.i18n (carregado antes do content.js)
├── _locales/
│   ├── en/messages.json     — 23 strings
│   ├── pt_BR/messages.json  — 23 strings (default)
│   └── es/messages.json     — 23 strings
└── icons/                   — 16x16, 48x48, 128x128 PNG
```

## Compatibilidade

| Recurso | Chrome | Brave | Edge | Firefox |
|---|---|---|---|---|
| Manifest V3 | ✅ | ✅ | ✅ | ✅ 121+ |
| `__MSG_*__` i18n | ✅ | ✅ | ✅ | ✅ |
| `chrome.storage` | ✅ | ✅ | ✅ | ✅ |
| `chrome.action.setBadgeText` | ✅ | ✅ | ✅ | ✅ |
| `chrome.downloads` | ✅ | ✅ | ✅ | ✅ |
| `chrome.scripting` | ✅ | ✅ | ✅ | ✅ |
| `MutationObserver` | ✅ | ✅ | ✅ | ✅ |

## Resultados dos testes

- **22/22** testes funcionais (Playwright headless)
- **10/10** testes em Firefox real + Pinterest real (non-headless)
- **21/21** testes de regressão completos (Playwright headless)
- 0 erros de console em todas as execuções
- 100% das imagens pinimg reescritas para `/originals/`
- 0 falsos positivos de webapp icons

## Limitações conhecidas

- **Pinterest login walls**: algumas páginas exigem login. Faça login antes de usar.
- **Pin IDs repetidos**: pins duplicados na mesma página são deduped automaticamente.
- **Vídeos (.mp4/.mov)**: a extensão baixa o thumbnail estático, não o vídeo.

## Build / Empacotamento

```bash
cd extension/
zip -r ../pinterest-pro-downloader.zip . -x "*.DS_Store"
```

## Privacidade

- **Não coleta dados** — nenhum analytics, nenhum tracking, nenhum servidor remoto.
- **Não modifica Pinterest** — apenas lê URLs de imagens públicas já carregadas.
- Permissões: `downloads`, `activeTab`, `scripting`, `storage`, `host_permissions` para pinterest.com e pinimg.com.

## Licença

MIT
