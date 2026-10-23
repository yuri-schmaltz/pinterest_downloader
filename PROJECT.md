# PROJECT.md — Pinterest Pro Downloader

**Repositório:** `yuri-schmaltz/pinterest_downloader`
**Licença:** MIT · **Python:** ≥ 3.10 · **Última atualização:** 2026-10-23
**Estado:** v2.0.4 publicada (2026-10-23) · branch `fix/ci-and-extension-repro` com as correções de estabilização e a primeira suíte de testes real, aguardando merge

---

## 1. O que é

Baixa imagens de quadros do Pinterest. Três produtos independentes que
compartilham o mesmo objetivo:

| Produto | Entry point | Natureza |
|---|---|---|
| **CLI** | `src/pinterest_board_dl.py` → `main()` | linha de comando, scriptável |
| **GUI** | `src/pinterest_board_gui.py` → `run()` | desktop PyQt6, seleção visual de quadros |
| **Extensão** | `extension/manifest.json` (MV3) | navegador, clica e baixa o que está visível |

Os três **não compartilham código**. A CLI/GUI são Python (Playwright +
requests); a extensão é JavaScript puro e funciona sem Python nenhum. Isso é
uma decisão consciente: a extensão é a via mais rápida para o usuário final
e não deve carregar o peso de um interpretador.

---

## 2. Inventário de features

### 2.1 Núcleo de coleta (Python)

| Feature | Módulo | Estado | Observação |
|---|---|---|---|
| Coleta de pins por scroll | `pinterest_board_dl._collect_pin_links_with_browser` | ✅ | Scroll stability com 20 rondas estáveis, detecção de altura, cap de 150s |
| Interceptação de rede (metadados de pin) | `pinterest_board_dl.handle_response` | ✅ | Captura `og:image` antes do download |
| Listagem de quadros do usuário | `pinterest_board_dl.collect_board_urls` | ✅ | Com título, thumbnail e contagem de pins |
| Extração de contagem de pins | `pinterest_board_dl.parse_pin_count` | ✅ | pt-BR e en ("1,2 mil", "1.2k", "3,4 mi") |
| Download paralelo de mídia | `pinterest_board_dl.download_media` | ✅ | `ThreadPoolExecutor`, retry com backoff |
| Detecção de perfil privado | `pinterest_board_dl.PrivateProfileError` | ✅ | Mensagem orienta a ativar login manual |
| Login manual interativo | `pinterest_board_dl.download_board` | ✅ | Pausa e aguarda o usuário no navegador |
| Reuso de browser entre quadros | `collect_pin_links` / `collect_board_urls` | ✅ | Parâmetro `browser` opcional |
| Cache de metadados de pin | `load_pin_cache` / `save_pin_cache` | ✅ | XDG (`~/.cache`) no Linux, `LOCALAPPDATA` no Windows |

### 2.2 Otimizações (as "ONDA"s)

| Feature | Módulo | Estado | Ativação |
|---|---|---|---|
| Rate limiting com sliding window | `rate_limiter.RateLimiter` | ✅ | `--rate-limiting` |
| Backoff exponencial em 429 | `rate_limiter` | ✅ | Automático |
| Adaptive workers (CPU/RAM) | `adaptive_workers.AdaptiveWorkerManager` | ✅ | `--adaptive-workers` |
| JSON logging estruturado | `json_logger.JSONLogger` | ✅ | `--json-log --log-file X` |

### 2.3 Extensão (JavaScript, MV3)

| Feature | Arquivo | Estado |
|---|---|---|
| Coleta de imagens visíveis via DOM | `extension/content.js` | ✅ |
| URL original de imagem (`getOriginalImageUrl`) | `extension/content.js` | ✅ |
| Hash do pin (`extractPinHash`) | `extension/content.js` | ✅ |
| Auto-scroll para carregar mais | `extension/content.js` | ✅ |
| Popup com seletor de pasta e limite de pins | `extension/popup.js` | ✅ |
| Background service worker | `extension/background.js` | ✅ |
| i18n en / es / pt-BR | `extension/lib/i18n.js` + `_locales/` | ✅ |
| "Load unpacked" / pacote Chrome | `scripts/build_release.sh` | ✅ |

---

## 3. Marcos

| Marco | Data | Conteúdo |
|---|---|---|
| **v1.0** | 2025-10-20 | Script único, CLI básica |
| **v1.1** | 2026-02-08 | GUI PyQt6, AppImage Linux, primeira release |
| **v2.0** | 2026-08-16 | Extensão MV3, restructure para `src/`, ONDA 5B–5E |
| **v2.0.1** | 2026-08-17 | Seletor de pasta + limite de pins na extensão |
| **v2.0.2** | 2026-08-17 | Tag criada, **build falhou** (ver §6) |
| **v2.0.3** | 2026-10-23 | Estabilização: build reproduzível, CI verde, packaging correto, i18n da extensão corrigido |
| **v2.0.4** | 2026-10-23 | Primeira release **com testes**: 85 testes + 69 checks, cobertura 23 % → 45 %; `lib/pin_utils.js` extraído; 3 bugs de verdade corrigidos |

---

## 4. Contratos de interface

Estes contratos são **estáveis** — mudar a assinatura quebra consumidores
externos. O job `smoke-import` do CI verifica que todo símbolo abaixo
continua exportado.

### 4.1 CLI

```
pinterest-board-dl [user] [-o OUT] [--headful] [--manual-login]
                   [--max-pins N] [--scroll-pause S] [--workers N]
                   [--boards-workers N] [--cache-dir DIR] [--no-cache]
                   [--json-log] [--log-file F] [--adaptive-workers]
                   [--rate-limiting]
```

O argumento posicional aceita **usuário** ou **URL de perfil**. O modo
"quadro único" (URL terminada em `/user/board/`) é detectado automaticamente.

### 4.2 API Python

```python
from pinterest_board_dl import (
    # resultado
    BoardDownloadResult,          # NamedTuple: (downloaded, total, verified, ...)
    DownloadOptions,              # dataclass de configuração
    PrivateProfileError,          # perfil privado sem login
    # coleta
    collect_pin_links,            # (board_url, browser=None, ...) -> list[str]
    collect_board_urls,           # (user, browser=None, ...) -> list[BoardMetadata]
    # download
    download_board,               # (board_url, options, ...) -> BoardDownloadResult
    download_user_boards,         # (user, options, ...) -> list[BoardDownloadResult]
    download_media,               # (media_url, out_dir, session, ...) -> bool
    resolve_images,               # (links, ...) -> dict[str, str | None]
    fetch_pin_media,              # (pin_url, session, ...) -> str | None
    # utilitários
    parse_pin_count, normalize_url, safe_name, slugify, out_dir_for,
    split_user_board_from_url, create_session,
    get_cache_dir, get_config_dir, get_cache_file_path,
    load_pin_cache, save_pin_cache,
    clear_intercepted_metadata, get_intercepted_metadata,
)

from rate_limiter import RateLimiter, RateLimitConfig, get_rate_limiter, reset_rate_limiter
from adaptive_workers import AdaptiveWorkerManager, WorkerMetrics, get_adaptive_manager, reset_adaptive_manager
from json_logger import JSONLogger, LogEntry, get_logger, reset_logger
```

**Invariantes de módulo:** os cinco módulos são instalados como *top-level*
(flat imports: `from json_logger import ...`). Não são um pacote — não
importe como `pinterest_board_dl.json_logger`.

### 4.3 Tipos de retorno

```python
class BoardMetadata(TypedDict):
    url: str; title: str; thumbnail_url: str
    pin_count: str; pin_count_int: int | None

class PinMetadata(TypedDict, total=False):
    id: str; url: str; image_url: str; title: str; description: str
```

`pin_count_int` é `None` quando o Pinterest exibe a contagem num formato
não-parseável — sempre trate como opcional.

### 4.4 Extensão (MV3)

Contrato declarado em `extension/manifest.json`:

- `content_scripts[0].js` = `["lib/i18n.js", "content.js"]` — **a ordem
  importa**: `i18n.js` define `window.__pbdI18n`, consumido por `content.js`
  e `popup.js` no load.
- `background.service_worker` = `background.js`
- `action.default_popup` = `popup.html`
- Permissões: `downloads`, `activeTab`, `scripting`, `storage`
- Hosts: `https://*.pinterest.com/*`, `https://*.pinimg.com/*`

Qualquer arquivo novo referenciado pelo manifest **tem de estar versionado**.
O `.gitignore` já contém `lib/` (do template setuptools) e `*.spec` — ambos
já causaram bugs reais. A regra `!extension/lib/` existe por isso, e o job
`extension` do CI falha o build se um arquivo referenciado não existir.

---

## 5. Estrutura do repositório

```
.
├── src/                          # aplicação Python (módulos soltos, flat imports)
│   ├── pinterest_board_dl.py     #   núcleo: scraper + CLI
│   ├── pinterest_board_gui.py    #   GUI PyQt6
│   ├── adaptive_workers.py       #   ONDA 5C
│   ├── rate_limiter.py           #   ONDA 5E
│   └── json_logger.py            #   ONDA 5B
├── extension/                    # extensão Chrome/Firefox MV3
│   ├── manifest.json
│   ├── lib/i18n.js               #   <- versionado; ver §4.4
│   ├── content.js  popup.js  popup.html  background.js
│   └── _locales/{en,es,pt_BR}/
├── tests/                        # 21 testes (pytest)
│   └── conftest.py               #   coloca src/ no sys.path
├── scripts/
│   ├── diagnose.py               #   diagnóstico de ambiente (offline)
│   ├── debug_pinterest.py        #   script de debug manual ( NÃO é teste )
│   ├── build_release.sh          #   empacota extensão + source
│   ├── build_all.sh              #   build PyInstaller + .deb
│   └── publish_{chrome,firefox}.py
├── hooks/                        # runtime hook do PyInstaller
├── docs/                         # runbooks e histórico das ONDAs
├── assets/icon.svg
├── PinterestDownloader.spec      # spec do PyInstaller (versionado!)
├── pyproject.toml
└── requirements.txt
```

---

## 6. Estado das releases

| Tag | Release | Artefatos | Situação |
|---|---|---|---|
| `v1.1.0` | sim | AppImage (358 MB) | ✅ funcional |
| `v2.0.0` | sim | zip Chrome + xpi + source | ⚠️ extensão funcionava; source **sem código** |
| `v2.0.1` | sim | idem v2.0.0 (assets nomeados `v2.0.0`) | ⚠️ idem |
| `v2.0.2` | **draft** | 3 assets | ❌ nunca publicada (build falhou) |
| `v2.0.3` | **sim** ✅ | AppImage 379 MB · .deb 339 MB · zip Windows 424 MB · zip Chrome · xpi · source 1,1 MB | ✅ **completa e verificada** |
| `v2.0.4` | **sim** ✅ | AppImage 379 MB · .deb 339 MB · zip Windows 424 MB · zip Chrome · xpi · source 1,1 MB | ✅ **completa e verificada** |

Causa raiz das falhas anteriores: o workflow de release rodava em
`ubuntu-20.04` (runner descontinuado), referenciava um
`PinterestDownloader.spec` que existia só na máquina do autor (engolido pelo
`.gitignore` `*.spec`), usava o caminho errado do ícone e copiava a pasta
`dist/` — em vez do conteúdo — para dentro do AppDir, o que fazia o
linuxdeploy abortar. **Tudo corrigido e verificado por build real.**

> A `v2.0.3` foi re-tagada: a primeira tentativa (2026-10-22) falhou no
> AppImage e chegou a publicar um `.exe` de 4 MB que, sozinho, não roda
> (no modo onedir do PyInstaller o executável precisa do `_internal/`).
> A release foi apagada e a tag recriada no commit corrigido — a versão
> antiga tinha 0 downloads.

### 6.1 A `v2.0.4`

A `v2.0.4` é a primeira release em que o código é **testado de verdade**:
85 testes em Python e 69 verificações da extensão, com a cobertura subindo
de 23 % para 45 %. Ela carrega três correções de bug que só apareceram
quando os testes existiram (títulos da GUI, `zip` incremental que deixava
arquivo morto no pacote, `libEGL` faltando na CI) e a extensão com
`lib/pin_utils.js` extraído para fora do IIFE do `content.js`.

As notas de release ficam em `RELEASE_NOTES.md`, na raiz, e são lidas
pelo workflow — **atualize esse arquivo a cada release**.

---

## 7. Documentos relacionados

| Documento | Assunto |
|---|---|
| [`PLANO-ESTABILIZACAO.md`](PLANO-ESTABILIZACAO.md) | prioridades P0–P3, o que falta |
| [`TEST_INFRA.md`](TEST_INFRA.md) | cobertura real, limites declarados, como rodar |
| [`docs/RUNBOOK_INSTALL.md`](docs/RUNBOOK_INSTALL.md) | instalação passo a passo |
| [`docs/RUNBOOK_TROUBLESHOOTING.md`](docs/RUNBOOK_TROUBLESHOOTING.md) | problemas comuns e soluções |
| [`docs/QUICK_REFERENCE.md`](docs/QUICK_REFERENCE.md) | comandos e flags, referência rápida |
| [`docs/ONDAS_COMPLETAS.md`](docs/ONDAS_COMPLETAS.md) | histórico das otimizações |
