# Infraestrutura e limites dos testes

Verificação local em **2026-11-06**, sobre as correções posteriores ao clone de `688243c`. Resultados locais não equivalem a CI remota nem validação dos artefatos publicados.

## Resultado reproduzido

| Verificação | Resultado |
|---|---|
| Python 3.12.3, Qt offscreen e Chromium | **218 passaram**, nenhum skip, 0 avisos de depreciação |
| Cobertura de `src/` | **67%** geral; scraper **57%**; GUI **72%** |
| Node: i18n + helpers de pins | **40 + 29 verificações** |
| Rust 1.99.1 | **53 testes** (22 unitários no core, 4 do browser, 3 da CLI, 24 de integração), todos aprovados com Chromium |
| Ruff / Black / mypy | Aprovados; mypy cobre scraper e app_version |
| Rustfmt / Clippy | Aprovados; Clippy com `-D warnings` |
| Versões | Manifest, Python, manifests Cargo e entradas locais do Cargo.lock sincronizados em 2.0.5 |
| Diagnóstico `--deep` | 13 checagens, nenhuma falha ou aviso |

Os avisos Python restantes vieram de `datetime.utcnow()`, removido de `json_logger.py`, `adaptive_workers.py` e `rate_limiter.py`; o formato dos timestamps foi preservado. Nenhum teste Rust da CLI é contado como teste unitário: os 13 unitários ficam no core, e os 23 restantes são de integração (browser, CLI, fluxo HTTP, coleta dinâmica e cache de metadados). O binário foi adicionalmente exercitado contra servidor local, verificando sucesso, extração vazia, workers zero e stream interrompido.

## O que cada camada prova

- **Python:** parsing/metadados, CLI, cache, workers, rate limiter, GUI e scraper em Chromium contra fixtures locais.
- **Cache e paralelismo (`test_cache_and_adaptive.py`):** `--cache-dir` grava e lê o cache no diretório informado; sem a opção vale o cache do sistema; e o gerenciador adaptativo altera o número real de tarefas em voo, não só a métrica.
- **Integridade Python (`test_download_integrity.py`):** servidor HTTP real local; interrupção de resposta, retry seguido de resposta completa, resposta vazia e colisões de prefixo/temporários no cache.
- **Despacho Python (`test_cli.py`):** URL de quadro chama `download_board`; usuário chama `download_user_boards`.
- **Versões (`test_version_sync.py`):** derivações Rust divergentes são rejeitadas por `--check` e reparadas pelo sync em cópias isoladas dos arquivos.
- **Node:** 40 verificações de i18n e 29 de helpers de URL/contagem, com objetos simulados.
- **Integração da extensão Python:** injeta scripts na ordem do manifest em Chromium com fixture; não instala a extensão.
- **Rust:** helpers de URL/contagem/tipo, parser de pins/quadros e fluxo HTTP perfil → quadro → imagem; limite por quadro, opções de cache e desativação do limitador, streams interrompidos/vazios, extração vazia, workers zero e colisões de cache.
- **Cache de metadados Rust (`metadata_cache.rs`):** gravação atômica e reuso na reexecução, descarte de cache corrompido, compatibilidade de formato com o Python, isolamento por `--cache-dir` e ausência de arquivo quando o cache está desligado. A reexecução sem nova ida à página do pin é verificada pelo contador de requisições do servidor de fixture.
- **Rate limiter Rust:** o teste verifica o contador de esperas do limitador, e não o relógio, para não depender da velocidade da máquina.
- **Coleta dinâmica Rust:** um feed lento não pode ser reportado como quadro vazio. A fixture serve um quadro cujo primeiro payload demora três segundos; sem a regra de estabilidade o teste falha com quadro vazio.
- **Paralelismo entre quadros (`board_concurrency.rs`):** o servidor de fixture registra o maior número de requisições atendidas ao mesmo tempo, então a concorrência é observada. Um worker não sobrepõe quadros; três workers sobrepõem. A ordem do relatório segue a descoberta, não o término.
- **Rate limiting Rust:** as janelas deslizantes de segundo, minuto e hora, o backoff exponencial com teto e o `Retry-After` em segundos e em data HTTP têm testes próprios, inclusive data no passado (tentar agora) e dia da semana incorreto (recusado).

## Executar

```bash
pip install -e ".[dev]"
python -m playwright install chromium
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q --cov=src --cov-report=term
node tests/test_extension_i18n.js
node tests/test_extension_pins.js
python scripts/sync_version.py --check
ruff check src/ tests/ scripts/
black --check src/ tests/ scripts/
mypy src/pinterest_board_dl.py src/app_version.py
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

Requer Qt e bibliotecas do Chromium disponíveis. Os testes de browser podem ser pulados se Chromium estiver ausente; confira a contagem de skips. Use Rust stable atual via rustup: Cargo 1.75 não lê o lockfile v4. A matriz Python 3.10/3.11/3.12 está no workflow; esta revisão local foi executada em Python 3.12.

## CI e empacotamento

`.github/workflows/tests.yml` define a matriz Python, smoke imports, integridade da extensão, versão, lint e Rust. O job Rust verifica formatação, Clippy e testes com lockfile. Os workflows alterados ainda precisam executar remotamente após integração.

```bash
bash scripts/build_release.sh
```

Esse comando gera ZIP Chrome, XPI experimental e source em `dist/`. O script verifica arquivos referenciados e a presença de Python, testes, manifests/crates Rust, spec PyInstaller e hooks no source. O workflow de release também define builds da CLI Rust para Linux e Windows. A execução local do empacotador não compila o desktop nem publica releases.

## Limites e próximos testes

1. **Pinterest atual:** fixtures são sintéticas; não há comprovação contra DOM/payloads de produção nem contas privadas/login.
2. **Rust:** coleta apenas metadados do HTML inicial. Sem JavaScript, scroll, paginação, browser ou autenticação; cobertura não significa paridade Python.
3. **Extensões instaladas:** APIs e testes com scripts injetados não cobrem o ciclo de vida real de uma extensão Chrome/Firefox. O XPI usa o manifest Chrome e não foi validado nem assinado.
4. **Distribuição:** AppImage, DEB, Windows e os novos binários Rust não foram validados em máquinas limpas nesta revisão.
5. **Arquivos anteriores:** a gravação temporária protege novos downloads; o cache ainda aceita arquivos antigos não vazios sem checksum e não repara retroativamente arquivos corrompidos.
6. **Performance:** não há benchmark comparativo atual para afirmar superioridade Rust, ganho de velocidade ou limites de hardware.
7. **Cache Python:** `--cache-dir` é encaminhado ao `resolve_images` e o padrão é o cache do sistema. Falta o cache versionado com invalidação segura previsto no plano de paridade.

Capturar fixtures reais e testar extensão instalada/artefatos em máquinas limpas são as próximas prioridades. Os números antigos de 21/85/202 testes em relatórios `ONDA*` pertencem ao histórico.
