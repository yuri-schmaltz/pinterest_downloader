# TEST_INFRA.md — Cobertura real e limites declarados

**Data da medição:** 2026-10-22 · **Commit:** `c2c07a5` (branch `fix/ci-and-extension-repro`)
**Comando:** `python -m coverage run --source=src -m pytest tests/ -q && python -m coverage report -m`

> Este documento declara **o que a suíte cobre e o que ela não cobre**.
> Números aqui são medidos, não estimados. Se a medição divergir, a medição
> está errada — reexecute o comando acima.

---

## 1. Panorama

| Métrica | Valor |
|---|---|
| Testes coletados | **21** |
| Testes passando | **21** (100%) |
| Falhas / erros de coleta | 0 |
| Tempo de execução | ~3 s |
| Dependências externas (rede/browser) | **nenhuma** |
| Cobertura total (`src/`) | **23 %** |

A cobertura total é baixa. Isso é honesto e está detalhado na §3.

---

## 2. Cobertura por módulo (medida)

| Módulo | Statements | Cobertura | Leitura |
|---|---|---|---|
| `src/rate_limiter.py` | 105 | **86 %** | ✅ bem coberto |
| `src/json_logger.py` | 85 | **85 %** | ✅ bem coberto |
| `src/adaptive_workers.py` | 109 | **74 %** | 🟡 bom |
| `src/pinterest_board_dl.py` | 783 | **16 %** | 🔴 núcleo do scraper, quase sem cobertura |
| `src/pinterest_board_gui.py` | 491 | **0 %** | 🔴 GUI intocada |
| **TOTAL** | **1 573** | **23 %** | |

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

### 3.3 `tests/test_robustness.py` — 1 teste

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
   nenhum teste.
2. **Nenhum teste abre o navegador.** O caminho de scroll, popups, lazy-load
   e login manual é **não testado**.
3. **A GUI não é exercitada.** Só se garante que o módulo importa.
4. **Não há teste de integração.** Não há teste que rode a CLI contra um
   quadro real nem que verifique arquivo baixado.
5. **Não há medição de performance no CI.** As tabelas de "93 % mais rápido"
   nos docs são de medições manuais antigas, não de um benchmark que rode
   hoje.
6. **Sem mutation testing.** Não sabemos se os testes falhariam se o código
   quebrasse de forma sutil.
7. **`test_scroll_detection` fixa um piso, não o valor.** `SCROLL_STABLE_ROUNDS`
   pode mudar sem quebrar o teste — de propósito, para que ajuste de tuning
   não quebre o pipeline.

---

## 7. Como rodar

```bash
# suíte completa
python -m pytest tests/ -v

# um arquivo
python -m pytest tests/test_11_rate_limiting.py -v

# cobertura
python -m coverage run --source=src -m pytest tests/ -q
python -m coverage report -m
python -m coverage html        # abre htmlcov/index.html

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
| 1 | Testes de integração com HTML salvo do Pinterest | cobre scroll, popups e parsing sem depender de rede | 1–2 dias |
| 2 | `pytest-qt` + `xvfb` para a GUI | hoje 0 % de cobertura | 2–3 dias |
| 3 | Fixture de HTML real do Pinterest em `tests/fixtures/` | base para o item 1 | 2 h |
| 4 | Testes do `content.js` (extensão) com jsdom | a extensão não tem nenhum teste | 1 dia |
| 5 | Mutation testing (`mutmut`) | medir a força real da suíte | 4 h |
| 6 | Benchmark automatizado | as métricas de performance nos docs estão desatualizadas | 1 dia |
