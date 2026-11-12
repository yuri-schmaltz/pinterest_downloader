# Referência rápida

Atualizada em **2026-11-06**, versão declarada 2.0.5. Para limites e arquitetura, veja [README](../README.md) e [PROJECT](../PROJECT.md).

## Python

```bash
pinterest-board-dl https://www.pinterest.com/usuario/quadro/
pinterest-board-dl --user usuario --adaptive-workers --rate-limiting
pinterest-board-dl usuario --headful --manual-login
pinterest-board-gui
pinterest-board-dl --help
```

| Opção | Default | Efeito |
|---|---|---|
| `-o, --out DIR` | `pins` | Pasta de saída |
| `--workers N` | 16 | Paralelismo de resolução/download |
| `--boards-workers N` | 1 | Paralelismo entre quadros, cada um abre um Chromium |
| `--max-pins N` | sem limite | Limite por quadro |
| `--scroll-pause S` | 1.2 | Pausa entre rolagens |
| `--cache-dir DIR` | cache do sistema | Diretório do cache de metadados (XDG/AppData quando omitido) |
| `--no-cache` | desligado | Ignora cache de metadados; reaproveita mídias existentes |
| `--adaptive-workers` | desligado | Ajusta workers por CPU/RAM |
| `--rate-limiting` | desligado | Ativa rate limiter |
| `--json-log` | desligado | Log estruturado |
| `--log-file F` | `download_log.json` | Destino do log |
| `--headful` | desligado | Browser visível |
| `--manual-login` | desligado | Login manual |

O cache de metadados é lido e gravado por `resolve_images` no diretório informado em `--cache-dir`. Quando a opção é omitida, vale o cache do sistema (XDG em Linux/macOS, `LOCALAPPDATA` no Windows). O arquivo é `.pinterest_cache.json` dentro desse diretório.

## Rust

Use Rust stable atual via rustup e o lockfile versionado.

```bash
cargo build --release --locked
./target/release/pinterest-cli https://www.pinterest.com/usuario/quadro/ -w 8 --max-pins 20
./target/release/pinterest-cli --user usuario --output downloads
./target/release/pinterest-cli --help
```

| Opção | Default | Efeito |
|---|---|---|
| `-u, --user USER` | — | Alternativa ao alvo posicional |
| `-o, --output DIR` | `downloads` | Pasta de saída |
| `-w, --workers N` | 8 | Downloads concorrentes, N > 0 |
| `--max-pins N` | sem limite | Limite por quadro, N > 0 |
| `--mode MODE` | `auto` | `auto`, `browser` ou `http` |
| `--headful` | desligado | Browser visível |
| `--manual-login` | desligado | Aguarda confirmação após login |
| `--no-cache` | desligado | Força download de mídia, ignorando arquivos existentes |
| `--no-metadata-cache` | desligado | Não usa o cache de metadados de pins |
| `--cache-dir DIR` | cache do sistema | Diretório do cache de metadados |
| `--no-rate-limit` | desligado | Desativa o limitador |
| `--json-log` / `--log-file F` | desligado | Eventos JSONL em stdout e em arquivo |

Rust usa Chromium no modo `auto` e `browser`; o modo `http` explícito é um snapshot
do HTML inicial e tem completude desconhecida. O cache de metadados é
`.pinterest_cache.json` no diretório informado em `--cache-dir` e tem o mesmo
formato do Python, de modo que o diretório pode ser compartilhado entre as duas
CLIs. A ausência de pins é um erro, e não uma conclusão bem-sucedida.

## Verificação e build

```bash
python scripts/diagnose.py --deep
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q --cov=src
node tests/test_extension_i18n.js
node tests/test_extension_pins.js
python scripts/sync_version.py --check
ruff check src/ tests/ scripts/
black --check src/ tests/ scripts/
mypy src/pinterest_board_dl.py src/app_version.py
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
bash scripts/build_release.sh
```

`build_release.sh` gera ZIP Chrome, XPI experimental e source completo em `dist/`. Os builds desktop e os binários Rust têm etapas próprias no workflow de release. Os módulos Python são instalados como top-level; pytest já configura `src/` no path.
