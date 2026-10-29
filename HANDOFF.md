# HANDOFF.md — Pinterest Pro Downloader

> Documento de passagem de bastão. Quem pegar o projeto deve conseguir
> rodar, testar, publicar e **não repetir as armadilhas** listadas na §7.
>
> Para o inventário de features e os contratos de interface, veja
> [`PROJECT.md`](PROJECT.md). Para o plano de trabalho e pendências, veja
> [`PLANO-ESTABILIZACAO.md`](PLANO-ESTABILIZACAO.md). Para o que a suíte
> cobre e o que ela **não** cobre, veja [`TEST_INFRA.md`](TEST_INFRA.md).

---

## 1. O que é, em 30 segundos

Baixa imagens e mídias de quadros do Pinterest. **Quatro produtos complementares**,
mesmo repositório:

| Produto | Onde | Stack |
|---|---|---|
| **Rust CLI** | `crates/pinterest-cli` | Rust puro, Tokio, reqwest, indicatif (alta performance) |
| **Python CLI** | `src/pinterest_board_dl.py` | Python, Playwright, requests |
| **Python GUI** | `src/pinterest_board_gui.py` | Python, PyQt6 (tema escuro moderno, 3 etapas) |
| **Extensão** | `extension/` | JavaScript puro, MV3, Chrome/Firefox |

A CLI e a GUI em Python compartilham o scraper e os recursos de Playwright. A extensão
**não usa Python** — é pura no navegador. A CLI em Rust é um executável nativo standalone
com download assíncrono e baixo consumo de CPU/memória.

---

## 2. Estado em 2026-10-29

| | |
|---|---|
| Branch padrão | `main` (`5a41f3e`) |
| Release no ar | **v2.0.5**, buildada do commit `5a41f3e` (6 artefatos verificados) |
| Branch de feature | `feat/rust-core` (`fe7defa`), com PR #11 aberto |
| CI | **verde**, 7 jobs bloqueantes no GitHub Actions |
| Testes | **202** em Python + **69** checks em Node + **3** em Rust |
| Cobertura | **63 %** no total · **72 %** na GUI · **48 %** no scraper |
| PR aberto | **PR #11** (Reescrita do núcleo e CLI em Rust puro) |

> **A release v2.0.5 já está no ar.** Contém a GUI moderna em 3 etapas com tema escuro,
> todas as 14 funções de alta complexidade refatoradas (P2.4 completo) e cobertura elevada
> para 63%. A branch `feat/rust-core` traz a implementação de alto desempenho em Rust puro.

---

## 3. Ambiente

### Python (CLI, GUI e Scraper)

```bash
# Python >= 3.10
pip install -e ".[dev]"          # inclui pytest, pytest-qt, pytest-cov, black, ruff, mypy
python -m playwright install chromium   # para testes do scraper e headless browser
```

O projeto usa **imports planos** (`from json_logger import ...`). `src/` precisa estar no `sys.path`.

### Rust (Core e CLI Nativa)

```bash
# Rust >= 1.80 (stable-x86_64-pc-windows-gnu ou MSVC)
cargo test                       # roda a suíte de testes do Rust (crates/pinterest-core)
cargo build --release            # gera target/release/pinterest-cli.exe
```

### Rodando a validação completa

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q     # suíte Python inteira (202 testes)
node tests/test_extension_i18n.js                          # checks de internacionalização
node tests/test_extension_pins.js                          # checks de extração de pins
python scripts/sync_version.py --check                     # gate de sincronização de versão
python scripts/diagnose.py                                # diagnóstico offline de ambiente
cargo test --workspace                                     # testes dos crates em Rust
```

---

## 4. Como o GitHub faz o trabalho

### A versão tem uma fonte só

```
extension/manifest.json      ← a fonte da verdade
├── pyproject.toml           derivado, conferido pelo job "version"
├── src/_version.py          derivado, conferido pelo job "version"
└── a tag do git             conferida pelo --tag
```

`scripts/sync_version.py` regenera as cópias. A CI **falha o build** se
qualquer uma divergir. O `src/_version.py` é o que o app mostra em
`--version` — ele viaja com o código e funciona dentro do AppImage
congelado.

> **Nunca** edite `pyproject.toml`, `src/_version.py` ou a tag à mão.
> Mude o manifest e rode `python scripts/sync_version.py`.

### Publicando uma release

1. Bump da versão em `extension/manifest.json` + `python scripts/sync_version.py`
2. Commit, push, **esperar o CI passar**
3. `git tag -a v2.0.x <commit> && git push origin v2.0.x`
4. O workflow `Multi-Platform Release` dispara (2 jobs: Linux e Windows)
5. **Baixar os assets de volta e verificar** (AppImage, deb, zip Windows, extensões, source)
6. Atualizar `RELEASE_NOTES.md` (o workflow lê esse arquivo) e os docs

---

## 5. Mapa do código

```
crates/
  pinterest-core/         núcleo assíncrono em Rust puro (parser DOM/JSON, rate-limiter, downloader)
  pinterest-cli/          CLI de alta velocidade em Rust nativo (clap derive, indicatif)

src/
  pinterest_board_dl.py   o scraper (CLI + motor da GUI). 880 linhas decompostas (< 15 complexidade)
  pinterest_board_gui.py  a GUI PyQt6, escura, em três etapas
  app_version.py          resolve a versão (gerado > manifest > metadata)
  _version.py             GERADO — não editar
  adaptive_workers.py     ajuste de workers por CPU/RAM
  rate_limiter.py         proteção contra 429
  json_logger.py          log estruturado

extension/
  manifest.json           a fonte da verdade da versão
  content.js              o script da página
  lib/i18n.js             traduções (fallback manual, sem depender de chrome.i18n)
  lib/pin_utils.js        helpers de URL dos pins — window.__pbdPinUtils
  background.js, popup.js, _locales/, icons/

scripts/
  sync_version.py         gate de versão
  build_release.sh        gera o zip da extensão e o tarball source
  diagnose.py             diagnóstico do ambiente, offline

hooks/
  playwright_browsers.py  roda dentro do app congelado: aponta o Playwright
                          para o Chromium embutido
```

---

## 6. A suíte

| Arquivo | Testes | Precisa de |
|---|---|---|
| `test_11_rate_limiting.py` | 10 | — |
| `test_core_features.py` | 10 | — |
| `test_robustness.py` | 1 | — |
| `test_scraper.py` | 26 | **Chromium** |
| `test_gui.py` | 29 | **Qt** (offscreen) |
| `test_gui_steps.py` | 39 | **Qt** (offscreen) |
| `test_extension_integration.py` | 13 | **Chromium** |
| `test_metadata_extraction.py` | 40 | — |
| `test_resolve_images.py` | 15 | — |
| `test_cli.py` | 19 | — |
| `test_extension_i18n.js` | 40 checks | Node |
| `test_extension_pins.js` | 29 checks | Node |
| `crates/pinterest-core` | 3 | Cargo / Rust |

Total: **202 testes em Python** + **69 checks em Node** + **3 testes Rust**, 100% PASS.

---

## 7. Armadilhas ⚠️

Cada uma destas custou tempo real. Leia antes de mexer em qualquer coisa.

### 7.1 `libEGL.so.1` — a CI quebra sem ele
O `pytest-qt` importa o `QtGui` já no `pytest_configure`. O runner do GitHub precisa
de pacotes explícitos (`libegl1 libxkbcommon0 libdbus-1-3 libxcb-*`).

### 7.2 `zip -r` ATUALIZA o arquivo, não recria
Um arquivo apagado continuaria no pacote. `scripts/build_release.sh` sempre remove
os zips antes de gerar.

### 7.3 `DELETE /releases/tags/{tag}` não existe
Sempre pegue o `id` em `GET /releases` e use `DELETE /releases/{id}`.

### 7.4 `importlib.metadata` mente num `pip install -e .`
O app lê `src/_version.py` gerado, **não** a metadata.

### 7.5 Folha de estilo do Qt: sem seletor = `* { ... }`
Use a paleta (`setPalette`) para pintar fundos, e seletores explícitos (`QFrame { ... }`)
para folhas de estilo.

### 7.6 `setGridSize(QSize(0, 0))` quebra o `ListMode`
Para desfazer o grid do `IconMode`, use `setGridSize(QSize())` — tamanho **nulo**.

### 7.7 QMessageBox modal trava o teste para sempre
Em modo `offscreen`, use o dublê `_FakeMessageBox`.

### 7.8 O `myPy` do PyQt6 tem stubs quebrados
A CI roda mypy apenas em `src/pinterest_board_dl.py` e `src/app_version.py`.

### 7.9 Proxy corporativo bloqueando `git push` (HTTP 403 MediaTypeBlocked)
Em redes corporativas filtradas por gateways (e.g. Skyhigh Secure Web Gateway), o
protocolo Git Smart HTTP (POST `git-receive-pack`) é bloqueado com 403.
**Solução:** Enviar commits e atualizar referências usando a API REST do GitHub
(`/git/blobs`, `/git/trees`, `/git/commits`, `/git/refs`).

### 7.10 Linker MinGW GCC 16 no Windows (`libgcc_eh.a`)
Ao compilar Rust com target `stable-x86_64-pc-windows-gnu` sob GCC 16, o linker pode
exigir `-lgcc_eh`. Caso ausente no MinGW, basta copiar `libgcc.a` para `libgcc_eh.a`
no diretório de bibliotecas do compilador GCC.

---

## 8. Em aberto

| # | Item | Onde |
|---|---|---|
| 1 | **Revisar e mergear PR #11 (`feat/rust-core`)** para unificar a CLI em Rust puro na `main` | GitHub PR #11 |
| 2 | **Capturar HTML real do Pinterest** para ampliar fixtures de teste contra drift de layout | `TEST_INFRA.md` §6 |
| 3 | **GUI pura em Rust (opcional)** com framework Iced ou Egui para substituir PyQt6 | Roadmap futuro |
| 4 | **Publicar a extensão no Chrome Web Store** — script pronto, requer credenciais Google | `PLANO-ESTABILIZACAO.md` P3.1 |
| 5 | **Assinar o XPI da extensão** para o portal Mozilla Add-ons | `PLANO-ESTABILIZACAO.md` P3.2 |

---

## 9. Glossário rápido

| Termo | Significado |
|---|---|
| **quadro** | board do Pinterest |
| **pin** | uma imagem ou mídia dentro de um quadro |
| **ONDA** | as fases históricas de implementação documentadas em `docs/` |
| **interceptação** | captura dos metadados dos pins durante a navegação, antes do download |
| **letterbox** | as barras de contraste que sobram quando uma imagem não é quadrada |
