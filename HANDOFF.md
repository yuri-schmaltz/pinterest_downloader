# Handoff — Pinterest Pro Downloader

Atualizado em **2026-11-06**. Versão declarada **2.0.5**.

## Ponto de partida

O commit `67329b1` integrou o PR #11 (`feat/rust-core`) na `main`. O clone analisado partiu de `688243c` de 2026-11-03. Referências anteriores ao PR #11 como aberto estão obsoletas.

Há quatro interfaces: CLI e GUI Python compartilham o scraper Playwright; a extensão roda no navegador; os crates Rust agora implementam coleta Chromium/CDP com JavaScript, rede e scroll, além de snapshot HTTP explícito. A paridade está em execução: login headful real, cache de metadados, GUI e validação no Pinterest continuam pendentes.

A auditoria local encontrou a CLI Rust passando um mapa vazio ao downloader, opções ignoradas, arquivos parciais tratados como cache e ausência de Rust na CI/source. As correções estão descritas em [PLANO-ESTABILIZACAO.md](PLANO-ESTABILIZACAO.md).

## Rodar e validar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
python scripts/diagnose.py
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
# Com Chromium disponível, inclui testes marcados como ignorados:
cargo test --workspace --all-features --locked -- --include-ignored
```

Use Rust stable atual via rustup. Os módulos Python são instalados como módulos top-level de `src/`; não são um pacote `src`. Testes Qt usam `QT_QPA_PLATFORM=offscreen`; os testes de browser podem ser pulados se Chromium estiver ausente. Confira o resumo de skips antes de interpretar um resultado verde.

## Versão e distribuição

`extension/manifest.json` é a fonte da versão. `python scripts/sync_version.py` sincroniza `pyproject.toml`, `src/_version.py`, os três manifests Cargo e suas entradas no lockfile. A CLI Rust usa `CARGO_PKG_VERSION`.

Para publicar, depois de revisar e integrar as alterações:

1. Atualize a versão no manifest e execute o sync.
2. Atualize `RELEASE_NOTES.md`, rode os checks e faça commit/push.
3. Aguarde a CI e crie a tag `v<versão>` no commit validado.
4. O workflow de release empacota Python, extensões, source e Rust Linux/Windows.
5. Baixe e teste cada artefato antes de considerá-lo validado.

A documentação anterior registra v2.0.5 como publicada com seis artefatos. O estado remoto das releases e da CI não foi revalidado nesta auditoria. Os novos builds Rust e a matriz de testes Chromium Linux/Windows ainda precisam rodar no GitHub após integração.

O source precisa incluir `crates/`, `Cargo.toml`, `Cargo.lock`, o spec PyInstaller e os hooks, além de Python e extensão. O script faz verificações explícitas desse conteúdo.

## Cuidados conhecidos

- Qt requer bibliotecas como `libEGL.so.1`, mesmo em offscreen.
- ZIP precisa ser recriado: atualizar um ZIP existente pode manter arquivos removidos.
- O executável PyInstaller depende da árvore `_internal/`; distribua o diretório completo.
- Arquivos `.part` não são cache. Downloads antigos não são verificados por checksum.
- O cache de metadados (Python e Rust) usa `.pinterest_cache.json` e o mesmo formato nos dois lados; a versão e a idade das entradas ficam em `.pinterest_cache_meta.json`, ao lado do mapa, e as entradas vencem depois de 30 dias por padrão (`--cache-ttl-days` nos dois lados). Um arquivo corrompido é descartado em vez de recuperado.
- Os testes de navegador usam fixtures sintéticas e scripts injetados; não substituem teste da extensão instalada nem teste no Pinterest real.
- O XPI ainda usa o manifest Chrome, sem assinatura nem validação Firefox.
- CRLF continuava no índice do commit de origem, apesar de `.gitattributes` exigir LF. O checkout foi normalizado; a mudança aparecerá no diff até ser commitada.

## Próximos trabalhos

Capturar fixtures reais, validar coleta no Pinterest, paginar a coleta dinâmica Rust, versionar o cache de metadados, testar artefatos em Windows/Linux e preparar manifests/assinatura das lojas. A interface Rust em egui já cobre perfil, seleção com capas, destino, progresso, cancelamento e login, e usa a mesma paleta da interface PyQt6. Os detalhes e limites de cobertura estão em [TEST_INFRA.md](TEST_INFRA.md).
