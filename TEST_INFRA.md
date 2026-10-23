# TEST_INFRA.md — Cobertura real e limites declarados

**Data da medição:** 2026-10-23 · **Branch:** `fix/ci-and-extension-repro`
**Comando:** `QT_QPA_PLATFORM=offscreen python -m coverage run --source=src -m pytest tests/ -q && python -m coverage report -m`

> Este documento declara **o que a suíte cobre e o que ela não cobre**.
> Números aqui são medidos, não estimados. Se a medição divergir, a medição
> está errada — reexecute o comando acima.

---

## 1. Panorama

| Métrica | Antes (2026-10-22) | Agora (2026-10-23) |
|---|---|---|
| Testes coletados | 21 | **85** (+ 69 checks em Node) |
| Testes passando | 21 | **85** (100 %) |
| Falhas / erros de coleta | 0 | 0 |
| Tempo de execução | ~3 s | ~26 s |
| Dependências externas (rede) | nenhuma | **nenhuma** |
| Browser | não usava | Chromium local, via `file://` |
| Cobertura total (`src/`) | 23 % | **45 %** |

Os 26 s são quase todos o browser: a coleta de pins espera a página
assentar antes de rolar, e cada coleta custa alguns segundos. Não há
acesso à rede em nenhum teste.

---

## 2. Cobertura por módulo (medida)

| Módulo | Statements | Antes | Agora | Leitura |
|---|---|---|---|---|
| `src/rate_limiter.py` | 105 | 86 % | **86 %** | ✅ bem coberto |
| `src/json_logger.py` | 85 | 85 % | **85 %** | ✅ bem coberto |
| `src/adaptive_workers.py` | 109 | 74 % | **74 %** | 🟡 bom |
| `src/pinterest_board_dl.py` | 792 | 16 % | **21 %** | 🟡 o núcleo ainda é o elo fraco |
| `src/pinterest_board_gui.py` | 491 | **0 %** | **61 %** | ✅ era o pior buraco |
| **TOTAL** | **1 582** | 23 % | **45 %** | |

### 2.1 O que mudou desde a medição anterior

| Entrega | Efeito |
|---|---|
| `tests/test_scraper.py` (22 testes) | fixtures de HTML local + Chromium real: a coleta de pins e a extração de quadros passaram a ser testadas de verdade |
| `tests/test_gui.py` (29 testes) | a GUI saiu de 0 % para 61 % |
| `tests/test_extension_integration.py` (13 testes) | os scripts da extensão carregados numa página real, num browser real |
| `tests/test_extension_pins.js` (29 checks) | a transformação de URL dos pins, que decide qual imagem o usuário baixa |
| `tests/test_extension_i18n.js` (40 checks) | as traduções, nos dois caminhos (com e sem `chrome.i18n`) |
| `_compute_scroll_stability` e `_extract_boards_from_page` extraídos | a aritmética do scroll virou função pura testável; a extração de quadros deixou de estar presa dentro de um closure |

### 2.2 O que a GUI ainda não cobre

Ficou de fora: o ciclo de download de verdade (a thread que chama o
scraper), o diálogo de login manual e o *worker* em background. O resto da
apresentação — lista de quadros, seleção, progresso, tratamento de erro —
está coberto.

### 2.1 O que o número de 16 % em `pinterest_board_dl.py` significa

O módulo tem 783 statements, dos quais ~430 estão no caminho de coleta com
Playwright (`_collect_pin_links_with_browser`, `collect_board_urls`,
`download_board`, `download_user_boards`) — código que **exige um navegador
real e o Pinterest online** para exercitar.

O que a suíte **cobre** nesse módulo são as funções puras e o contrato:
`parse_pin_count`, `normalize_url`, `safe_name`, `slugify`,
`out_dir_for`, `split_user_board_from_url`, o contrato de `DownloadOptions`,
o cache, e as **assinaturas** de `collect_pin_links`/`collect_board_urls`.

O que a suíte **não cobre**: o caminho de scraping real, o download real,
a interação com popups, o login manual, a detecção de perfil privado.

### 2.2 Por que a GUI está em 0 %

A GUI exige um display. Testá-la exigiria `pytest-qt` + `xvfb`, e o time
de frontend nunca chegou a criar esses testes. **Limitação declarada, não
omissão.** O CI não exercita a GUI — a garantia que existe para ela é de
outro tipo: o job `smoke-import` importa `pinterest_board_gui` e falha se o
módulo não importar (ver §5).

---

## 3. Inventário dos 21 testes

### 3.0 Mapa dos arquivos de teste

| Arquivo | Testes | Depende de | Cobre |
|---|---|---|---|
| `tests/test_11_rate_limiting.py` | 10 | — | rate limiter (ONDA 5E) |
| `tests/test_core_features.py` | 10 | — | constantes, cache, contrato, layout do pacote |
| `tests/test_robustness.py` | 1 | — | parser de contagem de pins |
| `tests/test_scraper.py` | 22 | **Chromium** | coleta de pins e extração de quadros |
| `tests/test_gui.py` | 29 | **Qt (offscreen)** | apresentação da GUI |
| `tests/test_extension_integration.py` | 13 | **Chromium** | scripts da extensão numa página real |
| `tests/test_extension_i18n.js` | 40 checks | Node | traduções (dois caminhos) |
| `tests/test_extension_pins.js` | 29 checks | Node | transformação de URL dos pins |

### 3.1 `tests/test_11_rate_limiting.py` — 10 testes (ONDA 5E)

| Teste | Cobre |
|---|---|
| `test_rate_limiter_initialization` | estado inicial do singleton |
| `test_rate_limiter_custom_config` | construtor com config customizada |
| `test_rate_limiter_acquire_basic` | aquisição de permissão |
| `test_rate_limiter_sliding_window` | janela deslizante de 1 s (5 req/s) |
| `test_rate_limiter_report_429` | registro de 429 e backoff exponencial |
| `test_rate_limiter_report_success` | reset do backoff após sucesso |
| `test_rate_limiter_thread_safety` | concorrência com múltiplas threads |
| `test_rate_limiter_get_stats` | estatísticas |
| `test_rate_limiter_save_stats` | persistência em JSON |
| `test_rate_limiter_singleton` | padrão singleton |

### 3.2 `tests/test_core_features.py` — 10 testes

| Teste | Cobre |
|---|---|
| `test_constants` | invariantes das constantes (timeout, retry, scroll) |
| `test_cache_functions` | round-trip do cache de metadados |
| `test_download_options` | defaults e customização de `DownloadOptions` |
| `test_retry_logic` | cálculo dos delays de backoff |
| `test_cli_help` | a CLI sobe, sai com 0 e expõe `--cache-dir` / `--no-cache` |
| `test_browser_reuse` | `collect_pin_links`/`collect_board_urls` aceitam `browser` opcional |
| `test_scroll_detection` | invariante do scroll (≥ 3 rondas) |
| `test_package_layout` | **integridade do layout** (ver §4) |
| `test_json_logger` | ciclo completo do logger estruturado (ONDA 5B) |
| `test_adaptive_workers` | métricas, ajuste e persistência (ONDA 5C) |

### 3.3 `tests/test_scraper.py` — 22 testes

O primeiro teste do scraper de verdade. Usa fixtures de HTML local
(`tests/fixtures/`) servidos por `file://` num Chromium real — sem rede.

| Grupo | Cobre |
|---|---|
| `TestScrollStability` (7) | a aritmética de quando parar o scroll: progresso zera o contador, altura estável conta 1, altura mudou conta 0,5, "Mais como esse" no fim da página conta 2, e o estado só éAdvance quando houve progresso |
| `TestCollectPinLinks` (4) | a coleta real: acha os 8 pins da fixture, ignora links que não são pin, respeita `max_pins`, devolve URLs absolutas do Pinterest |
| `TestExtractBoards` (11) | a extração real: acha os quadros, exclui as abas de navegação, exclui slugs com `_`, ignora outros usuários, lê título (com e sem `<h2>`), thumbnail e contagem de pins, e o `pin_count_int` bate com o `parse_pin_count` |

**As fixtures são o contrato.** Elas reproduzem o DOM que o scraper espera
(`<a href="/pin/ID">`, `__PWS_DATA__`, `h2` para título, a linha de contagem
de pins, os slugs de navegação). Se o scraper mudar o que espera do DOM, a
fixture tem de mudar junto — e o teste avisa.

### 3.4 `tests/test_gui.py` — 29 testes

A GUI saiu de 0 % para 61 %. Roda com o platform plugin `offscreen`, sem
display e sem `xvfb`.

| Grupo | Cobre |
|---|---|
| `TestMainWindow` (3) | a janela constrói, tem as duas colunas, e o botão iniciar começa desabilitado |
| `TestBoardList` (8) | a lista de quadros: quantidade, título + contagem, normalização da URL, limpeza de quebras de linha e espaços extras, lista vazia desabilita o início |
| `TestProgressSlots` (10) | os slots de progresso: barra com o total, total zero, valor limitado ao máximo, conclusão, contagem de pins, erro e cancelamento |
| `TestSelectionState` (5) | a seleção: começa desmarcada, marcar habilita o início, desmarcar desabilita, `selected_urls` acompanha os checkboxes |

> O `on_error` abre um `QMessageBox` **modal** — em modo offscreen isso
> trava o teste para sempre. O teste substitui o diálogo por um duble.

### 3.5 `tests/test_extension_integration.py` — 13 testes

Os scripts reais da extensão (`lib/i18n.js` → `lib/pin_utils.js` →
`content.js`), carregados na ordem do manifest, numa página de fixture, num
Chromium real.

| Grupo | Cobre |
|---|---|
| `TestManifestContract` (4) | o manifest é válido, todo arquivo referenciado existe, e os helpers são carregados **antes** do `content.js` |
| `TestScriptsLoad` (4) | as APIs são expostas, o content script roda sem erro, a barra é traduzida, e não há erro de JS na página |
| `TestHarvesting` (5) | a contagem de imagens de pin, o fingerprint deduplicado, a normalização para `/originals/`, e a ausência de avatar/ícone/host externo |

### 3.6 `tests/test_robustness.py` — 1 teste

| Teste | Cobre |
|---|---|
| `test_parse_pin_count` | 12 formatos de contagem de pins (pt-BR e en) |

---

## 4. O teste de integridade (`test_package_layout`)

Substituiu `test_diagnostics_script`, que verificava um arquivo
(`diagnostics.py`) removido de propósito no commit `9fb4c3e`.

Cobre o **método de falha real** do projeto, não uma feature:

1. Os cinco módulos do `src/` existem e são importáveis.
2. Todo arquivo referenciado por `extension/manifest.json` — content
   scripts, service worker, popup — **existe no repositório**.
3. Todo `<script src=...>` do `popup.html` **existe no repositório**.

**Teste negativo verificado:** removendo `extension/lib/i18n.js`, o teste
falha com:

```
AssertionError: extension/manifest.json references 'lib/i18n.js' but it is
not in the repository -- the extension would fail to load. Check that the
file is tracked by git (see 'git check-ignore -v extension/lib/i18n.js').
```

Esse foi exatamente o bug que quebrou a release v2.0.x: o `.gitignore`
herdado do setuptools contém `lib/`, que casa com `extension/lib/` em
qualquer nível de diretório.

---

## 5. Gates de CI (o que protege o que)

O CI não é só a suíte. São quatro jobs, todos bloqueantes:

| Job | Protege | Como |
|---|---|---|
| `test` | comportamento das funções puras | pytest em Python 3.10 / 3.11 / 3.12 |
| `smoke-import` | **contrato de API** | importa os 5 módulos e confirma que 17 símbolos públicos ainda existem |
| `extension` | **empacotamento** | manifest/popup referenciam só arquivos presentes **e versionados**; constrói o zip e confere `lib/i18n.js` dentro |
| `lint` | estilo e tipos | `black --check`, `ruff check`, `mypy` — sem `\|\| true` |

O job `smoke-import` é o que teria pegado o restructure para `src/` que
quebrou todos os imports do projeto de uma vez.

---

## 6. Limites declarados

O que **esta suíte não garante** — leia antes de confiar em algo:

1. **Nenhum teste toca a rede.** Nenhuma requisição ao Pinterest é feita.
   Uma mudança no layout do Pinterest pode quebrar o scraper sem quebrar
   nenhum teste — as fixtures são sintéticas, não HTML real capturado.
2. **O browser é real, a página não é.** O scroll, os popups e o lazy-load
   são exercitados contra uma fixture estática. O caminho contra o Pinterest
   de verdade continua **não testado**.
3. **O download real não é testado.** Nenhum teste baixa um arquivo, verifica
   o conteúdo salvo ou confere a contagem final de pins.
4. **A GUI não é testada de ponta a ponta.** A apresentação é coberta; o
   ciclo de download (thread, worker, login manual) não é.
5. **A extensão não é testada no navegador real com a extensão carregada.**
   Os scripts são carregados via `add_script_tag`, o que não exercita o
   `chrome.*` de verdade.
6. **Não há medição de performance no CI.** As tabelas de "93 % mais rápido"
   nos docs são de medições manuais antigas, não de um benchmark que rode
   hoje.
7. **Sem mutation testing.** Não sabemos se os testes falhariam se o código
   quebrasse de forma sutil.
8. **`test_scroll_detection` fixa um piso, não o valor.** `SCROLL_STABLE_ROUNDS`
   pode mudar sem quebrar o teste — de propósito, para que ajuste de tuning
   não quebre o pipeline.

---

## 7. Como rodar

```bash
# suíte completa (precisa do Chromium para os testes do scraper
# e do platform offscreen para os da GUI)
python -m playwright install chromium
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v

# um arquivo
python -m pytest tests/test_11_rate_limiting.py -v

# cobertura
python -m coverage run --source=src -m pytest tests/ -q
python -m coverage report -m
python -m coverage html        # abre htmlcov/index.html

# testes da extensão (Node puro, sem dependências)
node tests/test_extension_i18n.js
node tests/test_extension_pins.js

# teste de integração da extensão (Chromium)
python -m pytest tests/test_extension_integration.py -v

# diagnóstico do ambiente (offline)
python scripts/diagnose.py
python scripts/diagnose.py --deep    # inclui subir o Chromium
python scripts/diagnose.py --json     # saída machine-readable

# lint (mesmos comandos do CI)
black --check --line-length 120 src/ tests/ scripts/
ruff check src/ tests/ scripts/
mypy src/pinterest_board_dl.py --ignore-missing-imports
```

### Por que `src/` aparece no path

Os módulos usam **flat imports** (`from json_logger import ...`), então
`src/` precisa estar no `sys.path`. Isso é garantido em três lugares
independentes, de propósito:

1. `tests/conftest.py` — cobre qualquer invocação do pytest;
2. `pyproject.toml` → `[tool.pytest.ini_options] pythonpath = ["src"]` —
   cobre pytest ≥ 7 a partir da raiz;
3. o `sys.path.insert` de cada arquivo de teste — cobre a execução direta
   (`python tests/test_x.py`), que o conftest não cobre.

> **Armadilha para quem mexer aqui:** se um teste novo for adicionado e
> placed em outro diretório, ele **não** vai encontrar os módulos sem
> repetir o `sys.path.insert`. É o mesmo mecanismo que quebrou a suíte
> inteira quando o código migrou para `src/`.

---

## 8. Backlog de testes

Prioridade para as próximas rodadas:

| # | Item | Por quê | Esforço |
|---|---|---|---|
| 1 | **Capturar HTML real do Pinterest** e usar como fixture | hoje as fixtures são sintéticas: um layout novo do Pinterest não é detectado | 2 h |
| 2 | Teste de download real (baixa um pin, confere o arquivo) | o download é a única parte sem nenhum teste | 1 dia |
| 3 | Exercitar a extensão carregada de verdade (Playwright com extensão) | hoje os scripts são injetados à mão, o `chrome.*` não é real | 1–2 dias |
| 4 | Mutation testing (`mutmut`) | medir a força real da suíte | 4 h |
| 5 | Benchmark automatizado | as métricas de performance nos docs estão desatualizadas | 1 dia |
| 6 | Cobrir o `download_media` e o `resolve_images` | 21 % do núcleo ainda é o maior buraco | 1 dia |
