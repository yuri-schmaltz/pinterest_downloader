# HANDOFF.md — Pinterest Pro Downloader

> Documento de passagem de bastão. Quem pegar o projeto deve conseguir
> rodar, testar, publicar e **não repetir as armadilhas** listadas na §7.
>
> Para o inventário de features e os contratos de interface, veja
> [`PROJECT.md`](PROJECT.md). Para o que ainda falta, veja
> [`PLANO-ESTABILIZACAO.md`](PLANO-ESTABILIZACAO.md). Para o que a suíte
> cobre e o que ela **não** cobre, veja [`TEST_INFRA.md`](TEST_INFRA.md).

---

## 1. O que é, em 30 segundos

Baixa imagens de quadros do Pinterest. **Três produtos independentes**, mesmo
código-fonte:

| Produto | Onde | Stack |
|---|---|---|
| **CLI** | `src/pinterest_board_dl.py` | Python, Playwright, requests |
| **GUI** | `src/pinterest_board_gui.py` | Python, PyQt6 (escuro) |
| **Extensão** | `extension/` | JavaScript puro, MV3, Chrome/Firefox |

A CLI e a GUI compartilham o scraper. A extensão **não usa Python** — é um
caminho separado, e por isso tem testes próprios em Node.

---

## 2. Estado em 2026-10-29

| | |
|---|---|
| Branch padrão | `main` (`1330a84`) |
| Release no ar | **v2.0.4**, buildada do commit `ef042b0` |
| Commits na `main` além da release | **7** (refactor do scraper, flags da CLI, redesenho da GUI, docs) |
| CI | **verde**, 7 jobs, 3 versões de Python |
| Testes | **198** em Python + **69** checks em Node |
| Cobertura | **57 %** no total · **72 %** na GUI |
| PR aberto | nenhum |

> **A release publicada não tem a GUI nova.** A v2.0.4 saiu do `ef042b0`,
> antes do fluxo de três etapas, do tema escuro e das miniaturas
> quadradas. Essas três coisas estão na `main` e **esperam uma v2.0.5**.

---

## 3. Ambiente

```bash
# Python >= 3.10
pip install -e ".[dev]"          # inclui pytest, pytest-qt, pytest-cov, black, ruff, mypy
python -m playwright install chromium   # so para os testes do scraper

# o Chrome/Chromium e necessario para a GUI e para os testes de scraper
```

O projeto usa **imports planos** (`from json_logger import ...`), não
pacotes. `src/` precisa estar no `sys.path` — isso é feito em três lugares
de propósito (barato contra breakage silencioso): `tests/conftest.py`,
`[tool.pytest.ini_options] pythonpath` no `pyproject.toml` e o
`sys.path.insert` de cada arquivo de teste.

### Rodando

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q     # suíte inteira
node tests/test_extension_i18n.js                          # checks da extensão
node tests/test_extension_pins.js
python scripts/sync_version.py --check                     # gate de versão
python scripts/diagnose.py                                # diagnóstico offline
bash scripts/build_release.sh                              # artefatos locais
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
congelado, onde não há metadata nem manifest no disco.

> **Nunca** edite `pyproject.toml`, `src/_version.py` ou a tag à mão.
> Mude o manifest e rode `python scripts/sync_version.py`.

### Publicando uma release

1. Bump da versão em `extension/manifest.json` + `scripts/sync_version.py`
2. Commit, push, **esperar o CI passar**
3. `git tag -a v2.0.5 <commit> && git push origin v2.0.5`
4. O workflow `Multi-Platform Release` dispara (2 jobs: Linux e Windows)
5. **Baixar os assets de volta e verificar** — o build passar não prova que
   o pacote está certo (já aconteceu: uma release publicou um `.exe` de
   4 MB que não rodava sozinho)
6. Atualizar `RELEASE_NOTES.md` (o workflow lê esse arquivo) e os docs

As notas de release ficam em `RELEASE_NOTES.md`, na raiz. **Atualize esse
arquivo a cada release** — o workflow o lê e coloca no corpo do release.
Se o arquivo faltar, o release sai sem as notas e sem quebrar.

---

## 5. Mapa do código

```
src/
  pinterest_board_dl.py   o scraper (CLI + motor da GUI). 810 linhas
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

### Contratos que importam

- **A extensão carrega `lib/i18n.js` → `lib/pin_utils.js` → `content.js`**, nessa
  ordem, e o manifest declara essa ordem. Duas coisas validam isso: o job
  `extension` da CI confere que todo arquivo referenciado está
  **rastreado no git** (o `lib/` do `.gitignore` já escondeu o
  `i18n.js` uma vez, e o zip publicado saiu quebrado), e
  `tests/test_extension_integration.py` confere a **ordem** num Chromium
  real.
- **`content.js` não pode ter lógica inline** — a extração de metadados
  morava num closure e era inalcançável de qualquer teste. Hoje está em
  `lib/pin_utils.js`, exposto como `window.__pbdPinUtils`.
- **Os nomes dos widgets da GUI não mudam** (`user_edit`, `selection_list`,
  `start_button`, `log_edit`…). O redesenho da GUI só trocou a
  organização visual; foi o que permitiu manter os 29 testes antigos
  passando sem tocar neles.

---

## 6. A suíte

| Arquivo | Testes | Precisa de |
|---|---|---|
| `test_11_rate_limiting.py` | 10 | — |
| `test_core_features.py` | 10 | — |
| `test_robustness.py` | 1 | — |
| `test_scraper.py` | 22 | **Chromium** |
| `test_gui.py` | 29 | **Qt** (offscreen) |
| `test_gui_steps.py` | 39 | **Qt** (offscreen) |
| `test_extension_integration.py` | 13 | **Chromium** |
| `test_metadata_extraction.py` | 40 | — |
| `test_resolve_images.py` | 15 | — |
| `test_cli.py` | 19 | — |
| `test_extension_i18n.js` | 40 checks | Node |
| `test_extension_pins.js` | 29 checks | Node |

**Nenhum teste toca a rede.** As fixtures de HTML são servidas por
`file://`. Isso é deliberado — a suíte precisa rodar em qualquer máquina.

Cobertura medida: `python -m coverage run --source=src -m pytest tests/ -q`

---

## 7. Armadilhas ⚠️

Cada uma destas custou tempo real. Leia antes de mexer em qualquer coisa.

### 7.1 `libEGL.so.1` — a CI quebra sem ele

O `pytest-qt` importa o `QtGui` já no `pytest_configure`, e o `libQt6Gui`
é ligado contra `libEGL`. O runner do GitHub **não tem** essa lib, e o
`playwright install --with-deps` cobre as dependências do *browser*, não
as do Qt.

```
ImportError: libEGL.so.1: cannot open shared object file: No such file or directory
```

O job `test` e o `smoke-import` instalam explicitamente:
`libegl1 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libxcb-icccm4
libxcb-cursor0 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1
libxcb-shape0`.

No sandbox local as libs do sistema **somem sozinhas** de tempos em
tempos — reinstale se o import do PyQt6 falhar do nada.

### 7.2 `zip -r` ATUALIZA o arquivo, não recria

```
$ zip -q -r p.zip lib/     # build 1
$ rm lib/apagado.js
$ zip -q -r p.zip lib/     # build 2
$ unzip -l p.zip | grep apagado
apagado.js          # ← continua no pacote!
```

Um arquivo apagado da extensão ficaria **para sempre** no pacote
publicado, e o build reportava sucesso. `scripts/build_release.sh` agora
remove os artefatos antes de zipar. **Não reintroduza `zip` sem isso.**

### 7.3 `DELETE /releases/tags/{tag}` não existe

Na API do GitHub só existe `DELETE /releases/{id}`. A chamada por tag
devolve **404 e não apaga nada** — e, pior, apagar a *tag* de uma release
publicada **rebaixa a release para draft** em vez de removê-la, com os
assets ainda anexados.

Sempre: pegue o `id` em `GET /releases` e use `DELETE /releases/{id}`.

### 7.4 `importlib.metadata` mente num `pip install -e .`

A metadata fica congelada na instalação. Aconteceu aqui: um `egg-info`
de **2.0.3** convivendo com um `pyproject.toml` de **2.0.4**. Quem
perguntasse ao pacote instalado receberia um número que não existe.

Por isso o app lê `src/_version.py` (gerado), **não** a metadata.

### 7.5 Folha de estilo do Qt: sem seletor = `* { ... }`

```python
widget.setStyleSheet("background: #F6F7F9;")   # NÃO
```

Isso vale como `* { background: #F6F7F9 }` para **todos os descendentes**
e **sobrescreve** o QSS dos botões dentro dele. O sintoma: os botões
ficam com a cor errada e parecem desabilitados.

Use a paleta (`setPalette`) para pintar o fundo de um widget, e um
seletor explícito (`QFrame { ... }`) quando for folha de estilo.

### 7.6 `setGridSize(QSize(0, 0))` quebra o `ListMode`

Todos os itens caem na mesma linha, um em cima do outro. Para desfazer
o grid do `IconMode`, use `setGridSize(QSize())` — tamanho **nulo** —
ou não chame o método.

### 7.7 QMessageBox modal trava o teste para sempre

Em modo `offscreen`, `dlg.exec()` fica esperando um clique que nunca vem.
`tests/test_gui.py` tem o duble `_FakeMessageBox`; use-o (`monkeypatch.setattr(gui, "QMessageBox", _FakeMessageBox)`).

### 7.8 O `myPy` do PyQt6 tem stubs quebrados

```
/usr/local/lib/python3.11/dist-packages/PyQt6/QtGui.pyi:4930: error:
'/' parameter must appear before '*' parameter  [syntax]
```

Não é o seu código. Por isso a CI roda mypy **só** em
`src/pinterest_board_dl.py` e `src/app_version.py` — nunca na GUI.

### 7.9 No sandbox

```bash
export PIP_INDEX_URL=https://pypi.org/simple/     # senão o pip não acha nada
pip install --break-system-packages <pacote>       # PEP 668
export GIT_SSL_NO_VERIFY=true                     # o git falha sem isso
```

E os tokens do GitHub no ambiente já morreram uma vez (401 nos três:
`GITHUB_TOKEN`, `GITHUB_PUSH_TOKEN`, `GITHUB_PAT`). **Se der 401, é o
token — não a rede.** Reponha no secret store e troque a URL do remote:

```bash
git remote set-url origin "https://x-access-token:<token>@github.com/yuri-schmaltz/pinterest_downloader.git"
```

---

## 8. Em aberto

| # | Item | Onde |
|---|---|---|
| 1 | **Publicar a v2.0.5** com a GUI nova (3 etapas, escura, miniaturas quadradas), o refactor do scraper e as flags `--version`/`--user`. A v2.0.4 no ar tem a GUI antiga | §4 |
| 2 | **Cobertura do scraper: 32 % → 50 %**. O download real e o parsing do HTML do Pinterest continuam sem teste | `TEST_INFRA.md` §6 |
| 3 | **Capturar HTML real do Pinterest** para usar de fixture — hoje as fixtures são sintéticas, então uma mudança no layout real do Pinterest não é detectada | `TEST_INFRA.md` §6 |
| 4 | **A extensão nunca foi testada com a extensão de verdade carregada** — os scripts são injetados à mão, o `chrome.*` não é real | `TEST_INFRA.md` §6 |
| 5 | **Refatorar as 5 funções que ainda passam de 15 de complexidade**: `_collect_pin_links_with_browser` (37), `collect_board_urls` (22), `download_board` (20), `_collect_with_page` (19), `_status_callback` (16) | `PLANO-ESTABILIZACAO.md` P2.4 |
| 6 | **Benchmark automatizado** — as tabelas de performance nos docs são de 2025 e não reproduzíveis | `PLANO-ESTABILIZACAO.md` P2.5 |
| 7 | **Publicar a extensão no Chrome Web Store** — o script existe, falta credencial OAuth2 do Google | `PLANO-ESTABILIZACAO.md` P3.1 |
| 8 | **Assinar o XPI** — a Mozilla exige assinatura; hoje sai sem assinar | `PLANO-ESTABILIZACAO.md` P3.2 |

Duas decisões que ficaram em aberto e valem uma resposta:

- O botão *Listar Quadros* está **só no passo 1**. Colocá-lo também na
  barra deixaria dois botões iguais.
- A cor de fundo das barras de *letterbox* da miniatura é `#22262E`, a
  mesma dos painéis. Mais contraste seria uma constante só.

---

## 9. Glossário rápido

| Termo | Significado |
|---|---|
| **quadro** | board do Pinterest |
| **pin** | uma imagem dentro de um quadro |
| **ONDA** | as fases de implementação que o autor documentou em `docs/ONDA_*.md` — são histórico, com banner |
| **interceptação** | captura dos metadados dos pins durante a navegação, antes do download |
| **capa** | a miniatura de um quadro |
| **letterbox** | as barras que sobram quando uma imagem não é quadrada |

---

## 10. Se você só quiser fazer uma coisa

**Publicar a v2.0.5.** É o que está em aberto há mais tempo e o que
traz mais valor imediato: o app no ar ainda tem a GUI de duas colunas e
o tema claro. O caminho está inteiro na §4 e o procedimento foi usado com
sucesso duas vezes (v2.0.3 e v2.0.4).

Antes de tagear, confira o passo 5 da §4 — **baixe os assets de volta e
verifique**. É o passo que pegou o `.exe` quebrado da v2.0.1.
