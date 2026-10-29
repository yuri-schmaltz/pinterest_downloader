# 🎯 QUICK REFERENCE

Referência rápida de comandos e flags do **Pinterest Pro Downloader v2.0.3**.

> Reescrito em 2026-10-22. A versão anterior era um resumo da "ONDA 1 e 2"
> (janeiro de 2026) e apontava para `python test_patches.py`, que nunca
> existiu.

---

## TL;DR

```bash
# diagnóstico (1s, offline)
python scripts/diagnose.py

# suíte
python -m pytest tests/ -q          # 21 passed

# um quadro
pinterest-board-dl https://www.pinterest.com/usuario/quadro/

# todos os quadros de um usuário
pinterest-board-dl --user usuario_pinterest

# com tudo ligado
pinterest-board-dl <URL> --workers 32 --adaptive-workers --rate-limiting --json-log
```

---

## Flags da CLI

| Flag | Default | Efeito |
|---|---|---|
| `-o, --out DIR` | `./pins` | pasta de saída |
| `--user NOME` | — | baixa todos os quadros públicos do usuário |
| `--max-pins N` | sem limite | limita pins por quadro |
| `--workers N` | 16 | paralelismo de resolução/download |
| `--boards-workers N` | 1 | paralelismo entre quadros (2–3; cada um abre um Chromium) |
| `--scroll-pause S` | 1.2 | pausa entre rolagens |
| `--cache-dir DIR` | `~/.cache/pinterest-downloader` | diretório do cache |
| `--no-cache` | desligado | ignora o cache de metadados |
| `--adaptive-workers` | desligado | ajusta workers por CPU/RAM |
| `--rate-limiting` | desligado | proteção contra HTTP 429 |
| `--json-log` | desligado | log estruturado |
| `--log-file F` | `download_log.json` | onde gravar o log JSON |
| `--headful` | desligado | navegador visível (debug/login) |
| `--manual-login` | desligado | pausa para login manual |

O argumento posicional aceita **usuário** ou **URL de perfil**. URL de quadro
(`/user/board/`) é detectada sozinha.

---

## Comandos de desenvolvimento

```bash
# testes
python -m pytest tests/ -v
python -m pytest tests/test_11_rate_limiting.py -v

# cobertura
python -m coverage run --source=src -m pytest tests/ -q
python -m coverage report -m
python -m coverage html

# lint (idêntico ao CI)
black --check --line-length 120 src/ tests/ scripts/
ruff check src/ tests/ scripts/
mypy src/pinterest_board_dl.py --ignore-missing-imports

# diagnóstico
python scripts/diagnose.py
python scripts/diagnose.py --deep
python scripts/diagnose.py --json

# build da extensão
bash scripts/build_release.sh          # gera dist/*.zip, *.xpi, *.tar.gz

# build do app desktop
PLAYWRIGHT_BROWSERS_PATH=~/.cache/ms-playwright \
  pyinstaller --noconfirm --clean PinterestDownloader.spec

# debug manual do scraper (abre o browser, tira screenshot)
python scripts/debug_pinterest.py --url https://www.pinterest.com/user/board/ --out /tmp/shot.png
```

---

## Constantes do núcleo

Definidas em `src/pinterest_board_dl.py`:

```python
PINTEREST_BASE_URL = "https://www.pinterest.com"

TIMEOUT_HTTP_GET = 25              # segundos (requests)
TIMEOUT_IMAGE_DOWNLOAD = 60        # segundos (requests)
TIMEOUT_PAGE_LOAD = 90_000         # ms (Playwright)
TIMEOUT_DOM_READY = 15_000         # ms (Playwright)

DOWNLOAD_RETRY_DELAY = 1.0         # base do backoff exponencial
DOWNLOAD_MAX_RETRIES = 1           # retries além da tentativa inicial

SCROLL_STABLE_ROUNDS = 20          # rondas estáveis para considerar o fim
SCROLL_HEIGHT_CHECK = True         # detecta a página pela altura
```

> `SCROLL_STABLE_ROUNDS` já foi 6 → 3 → 20. Acompanhe no histórico:
> `git log -p -S SCROLL_STABLE_ROUNDS src/pinterest_board_dl.py`

---

## Arquivos e diretórios

| Caminho | Conteúdo |
|---|---|
| `~/.cache/pinterest-downloader/.pinterest_cache.json` | cache pin → url da imagem |
| `./rate_limit_stats.json` | estatísticas de 429 (gravado no diretório atual) |
| `./.worker_metrics.json` | métricas dos adaptive workers (diretório atual) |
| `./pins/<usuario>/<quadro>/` | imagens baixadas |
| `./download_log.json` | log estruturado (quando `--json-log`) |

> O cache de metadados vai para o diretório de cache do sistema
> (`~/.cache` no Linux, `%LOCALAPPDATA%` no Windows) e pode ser redigido com
> `--cache-dir`. Já os arquivos de estatísticas e métricas usam caminho
> relativo e saem no **diretório de onde você chamou o comando**.

---

## Estrutura do código

```
src/pinterest_board_dl.py     núcleo: scraper + CLI
src/pinterest_board_gui.py    GUI PyQt6
src/json_logger.py            log estruturado
src/adaptive_workers.py       workers por CPU/RAM
src/rate_limiter.py           sliding window + backoff 429
extension/                    extensão MV3
tests/                        21 testes
```

**Flat imports:** os módulos se importam como `from json_logger import ...`,
então `src/` precisa estar no `sys.path`. Ao criar um teste novo, repita:

```python
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
```

---

## Links

| Documento | Assunto |
|---|---|
| [../PROJECT.md](../PROJECT.md) | features, marcos, contratos de interface |
| [../PLANO-ESTABILIZACAO.md](../PLANO-ESTABILIZACAO.md) | prioridades P0–P3 |
| [../TEST_INFRA.md](../TEST_INFRA.md) | cobertura real e limites |
| [RUNBOOK_INSTALL.md](RUNBOOK_INSTALL.md) | instalação passo a passo |
| [RUNBOOK_TROUBLESHOOTING.md](RUNBOOK_TROUBLESHOOTING.md) | problemas comuns |
