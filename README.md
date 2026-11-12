# Pinterest Pro Downloader

[![Tests & Quality](https://github.com/yuri-schmaltz/pinterest_downloader/actions/workflows/tests.yml/badge.svg)](https://github.com/yuri-schmaltz/pinterest_downloader/actions/workflows/tests.yml)

Baixa mídias de quadros públicos do Pinterest. Versão declarada: **2.0.5**.

| Interface | Implementação | Uso e limites |
|---|---|---|
| CLI Python | Playwright + requests | Coleta dinâmica de quadros e perfis, scroll e login manual |
| GUI Python | PyQt6, mesmo motor da CLI | Perfil → escolher quadros → baixar |
| CLI Rust | Tokio + reqwest + Chromium/CDP | Coleta dinâmica por DOM/rede e scroll; modo HTTP explícito para snapshots. Migração em andamento |
| Extensão | JavaScript, Manifest V3 | Coleta no navegador; Chrome empacotado e XPI experimental |

Os testes usam fixtures e servidores locais. Eles não comprovam compatibilidade com o layout atual do Pinterest. A implementação Rust tem testes HTTP e Chromium com fixtures locais, mas ainda não tem paridade completa com o produto Python nem benchmarks comparativos.

## Instalação Python

Requer Python ≥ 3.10 e as bibliotecas de sistema do Qt/Chromium.

```bash
git clone https://github.com/yuri-schmaltz/pinterest_downloader.git
cd pinterest_downloader
python3 -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m playwright install chromium
python scripts/diagnose.py
```

```bash
# Quadro único
pinterest-board-dl https://www.pinterest.com/usuario/quadro/

# Quadros públicos de um perfil
pinterest-board-dl --user usuario --adaptive-workers --rate-limiting

# Login manual, se necessário
pinterest-board-dl usuario --headful --manual-login

pinterest-board-gui
pinterest-board-dl --help
```

O Python oferece cache de metadados, workers adaptativos e logs JSON. `--no-cache` desativa o cache de metadados; arquivos já presentes continuam sendo reaproveitados. `--cache-dir DIR` aponta o cache para outro diretório; sem a opção vale o cache do sistema (XDG em Linux/macOS, `LOCALAPPDATA` no Windows). Com `--adaptive-workers`, o número de tarefas em voo acompanha o ajuste do gerenciador. Downloads novos são gravados em temporários e publicados somente quando a resposta termina, sem considerar arquivos `.part` como concluídos. Arquivos antigos não são revalidados por checksum.

## CLI Rust

Use o toolchain **stable atual via rustup**. O lockfile usa formato 4; o Cargo 1.75 fornecido por algumas distribuições não o suporta. O projeto ainda não valida uma versão mínima de Rust em CI.

```bash
cargo build --release --locked
./target/release/pinterest-cli https://www.pinterest.com/usuario/quadro/ -w 8 --max-pins 20
./target/release/pinterest-cli --user usuario --output downloads
./target/release/pinterest-cli --help
```

O modo padrão `auto` usa Chromium para não presumir que o HTML inicial contém todos os pins. O browser é localizado por `--browser-executable`, `PINTEREST_CHROMIUM`, instalação do sistema ou cache Playwright já existente; Python/Node não são necessários para usar o binário Rust. Sem browser instalado, a CLI informa como configurar o caminho. Chromium ainda não é baixado/empacotado automaticamente pela versão Rust.

```bash
# Coleta dinâmica e eventos JSONL
./target/release/pinterest-cli usuario/quadro --mode browser --json-log

# Browser visível; login manual aguarda Enter e pode ser cancelado com Ctrl+C
./target/release/pinterest-cli usuario --headful --manual-login

# Snapshot explícito, sem browser: completude desconhecida, código de saída 6
./target/release/pinterest-cli usuario/quadro --mode http
```

A coleta acumula IDs entre páginas/scroll e captura respostas JSON. Pins sem metadados podem ser resolvidos pela página do pin e metatags. Cookies da sessão são encaminhados ao downloader. O protocolo de login está implementado, mas o fluxo headful autenticado ainda precisa de validação interativa; a CI cobre browser headless.

`--max-pins` limita cada quadro; `--no-cache` preserva a semântica Rust de forçar download de mídia; `--no-rate-limit` desativa o limitador; `--boards-workers` processa vários quadros ao mesmo tempo, cada um com o próprio browser. Use `--scroll-pause`, `--collection-timeout`, `--headful`, `--browser-executable`, `--json-log` e `--log-file` conforme `--help`. O log Rust é JSONL versionado, diferente do arquivo JSON da implementação Python.

O modo automático ainda não possui fast path HTTP com prova de completude. Estabilidade/timeout produzem completude desconhecida; um limite pedido é informado separadamente. Código 0 indica conclusão conhecida/limitada sem falhas, 6 indica resultado parcial/desconhecido, 7 indica extração não comprovada; cancelamento retorna 130. Falhas de browser e autenticação usam 3 e 4. A interpretação de fim de feed ainda depende de fixtures sintéticas e precisa ser validada no Pinterest atual.

A saída Rust mantém `downloads/<usuario>_<quadro>/`. O cache de metadados é `.pinterest_cache.json` no diretório de `--cache-dir` (cache do sistema por padrão) e tem o mesmo formato do Python, então o diretório pode ser compartilhado entre as duas CLIs; `--no-metadata-cache` desliga apenas esse cache, sem alterar `--no-cache`. O limitador usa janelas deslizantes de segundo, minuto e hora, com backoff exponencial e `Retry-After`. Cache persistente com expiração, workers adaptativos, GUI e migração dos arquivos estão pendentes. O progresso está registrado em [docs/PLANO-PARIDADE-RUST.md](docs/PLANO-PARIDADE-RUST.md) e no [contrato de paridade](docs/CONTRATO-PARIDADE.md).

## Extensão

Para Chrome, carregue `extension/` em `chrome://extensions` → modo do desenvolvedor → carregar sem compactação. Para gerar ZIP Chrome e XPI:

```bash
bash scripts/build_release.sh
```

O XPI atual reutiliza o manifest Chrome, não é assinado e ainda precisa de validação de compatibilidade Firefox. Gerar o arquivo não comprova que ele funciona no Firefox. Veja [extension/README.md](extension/README.md).

## Desenvolvimento e verificação

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q --cov=src
node tests/test_extension_i18n.js
node tests/test_extension_pins.js
python scripts/sync_version.py --check
ruff check src/ tests/ scripts/
black --check src/ tests/ scripts/
mypy src/pinterest_board_dl.py src/app_version.py
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-features --locked
# Inclui testes que exigem Chromium instalado:
cargo test --workspace --all-features --locked -- --include-ignored
```

As medições e os limites dos testes estão em [TEST_INFRA.md](TEST_INFRA.md). Os workflows versionados validam Python, extensão, versões e Rust. O workflow de release inclui builds desktop Python, extensões, source e CLI Rust Linux/Windows; alterações locais nesses workflows só passam a valer após push. Nenhuma nova release é criada ao executar testes ou builds locais.

## Documentação

- [PROJECT.md](PROJECT.md): arquitetura e contratos.
- [HANDOFF.md](HANDOFF.md): retomada do trabalho e publicação.
- [PLANO-ESTABILIZACAO.md](PLANO-ESTABILIZACAO.md): correções e pendências.
- [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md): comandos e opções.
- [docs/RUNBOOK_INSTALL.md](docs/RUNBOOK_INSTALL.md): instalação.
- [docs/RUNBOOK_TROUBLESHOOTING.md](docs/RUNBOOK_TROUBLESHOOTING.md): diagnóstico.

Os guias `ONDA*` e relatórios antigos em `docs/` são registros históricos, com métricas da época. Licença [MIT](LICENSE).
