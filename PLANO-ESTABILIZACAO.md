# PLANO-ESTABILIZACAO.md

**Data:** 2026-10-29 · **Estado atual:** v2.0.5 na `main` (`5a41f3e`), branch `feat/rust-core` com reescrita em Rust puro (PR #11)
**Referência:** [`PROJECT.md`](PROJECT.md) · [`TEST_INFRA.md`](TEST_INFRA.md)

---

## Situação

A `main` estava com **tudo vermelho desde 2026-02-07**: CI falhando em
todos os pushes, suíte coletando 0 testes, extensão não reproduzível a
partir do repositório, e release quebrada em 3 tags seguidas. O código em si
era razoável — o problema era o entorno.

O processo de estabilização completou as etapas críticas (P0, P1, P2) e entregou
a versão estável **v2.0.5**, além de iniciar a modernização para Rust puro (P4):

| # | Entrega | Estado |
|---|---|---|
| 1 | `extension/lib/i18n.js` e `pin_utils.js` versionados | ✅ |
| 2 | Suíte expandida de 0 para 202 testes automatizados (100% pass) | ✅ |
| 3 | CI com 7 jobs bloqueantes em 3 versões de Python | ✅ |
| 4 | Releases v2.0.4 e v2.0.5 criadas e validadas com 6 artefatos cada | ✅ |
| 5 | Redesenho completo da GUI em 3 etapas com tema escuro | ✅ |
| 6 | Refatoração completa de complexidade ciclomática (P2.4) | ✅ |
| 7 | Reescrita assíncrona do núcleo e CLI em Rust puro (`feat/rust-core`) | ✅ |

---

## P0 — Bloqueia release

> **✅ P0 e P0.9 entregues.** A `v2.0.5` foi publicada com 6 artefatos
> verificados, buildados a partir da `main` no commit `5a41f3e`.

| # | Item | Por que é P0 | Esforço | Estado |
|---|---|---|---|---|
| P0.1 | **Merge da branch de estabilização** | contém os fixes de ambiente | 10 min | ✅ PR #10 mergeado |
| P0.2 | **Fechar os 7 PRs antigos** | abertos há meses, baseados na arquitetura legada | 30 min | ✅ fechados com justificativa |
| P0.3 | **Publicar a `v2.0.4`** | primeira release funcional com testes reais | 1 h | ✅ 6 artefatos verificados |
| P0.4 | **Sincronização de versão** | `pyproject.toml` e `manifest.json` com fonte única | 15 min | ✅ `scripts/sync_version.py` |
| P0.5 | **Publicar a `v2.0.5`** | nova GUI em 3 etapas, scraper modular e 202 testes | 1 h | ✅ 6 artefatos verificados |

### Critérios de aceite cumpridos (v2.0.5)

- [x] Versão 2.0.5 em `manifest.json`, `pyproject.toml` e `src/_version.py`
- [x] Tag `v2.0.5` criada na `main` e workflow `release.yml` concluído
- [x] AppImage gerado (380 MB) e verificado com Chromium
- [x] `.deb` gerado (340 MB) para Linux Debian/Ubuntu
- [x] Zip Windows gerado (425 MB) com árvore onedir completa
- [x] Extensões compactadas (Chrome zip e Firefox xpi)
- [x] Source tarball verificado
- [x] Notas de release em `RELEASE_NOTES.md`

---

## P1 — Dívida que incomoda

| # | Item | Detalhe | Esforço | Estado |
|---|---|---|---|---|
| P1.1 | **Reescrever o README** | layout atualizado, instruções de CLI, GUI e Rust | 2 h | ✅ |
| P1.2 | **Sanear `docs/`** | runbooks operacionais alinhados com o código real | 3 h | ✅ |
| P1.3 | **Deduplicar as dependências** | separação de `requirements-dev.txt` e pyproject | 20 min | ✅ |
| P1.4 | **Unificar a versão** | gerada do manifest via script automatizado | 1 h | ✅ |
| P1.5 | **Fechar o gap de `lib/` no `.gitignore`** | whitelist explícita e validação em CI | 30 min | ✅ |
| P1.6 | **`extension/README.md`** | guia da extensão e checklist de publicação | 1 h | ✅ |
| P1.7 | **Gate de versão na CI** | job bloqueante conferindo tag e manifest | 1 h | ✅ |

---

## P2 — Qualidade

| # | Item | Detalhe | Estado |
|---|---|---|---|
| P2.1 | **Cobertura do scraper** | ampliada para 48% com fixtures e Chromium real | ✅ |
| P2.2 | **Testes da GUI (72%)** | `pytest-qt` em modo `offscreen` | ✅ |
| P2.3 | **Testes da extensão** | 82 checks em Node + 13 de integração | ✅ |
| P2.4 | **Refatorar funções complexas (C901)** | todas as funções com complexidade > 15 decompostas em helpers modulares no scraper | ✅ **completo** |
| P2.6 | **`--version` na CLI** | implementado com `src/app_version.py` | ✅ |
| P2.7 | **`--user` na CLI** | argumento nomeado implementado | ✅ |
| P2.8 | **Parser da CLI isolado** | `build_arg_parser()` testável sem browser | ✅ |
| P2.9 | **Redesenhar layout da GUI** | fluxo de 3 etapas com seleção visual | ✅ |
| P2.10 | **Tema escuro integrado** | paleta única com contraste acessível | ✅ |
| P2.11 | **Miniaturas quadradas** | `square_thumbnail()` sem distorção | ✅ |

---

## P4 — Modernização de Performance (Rust Puro)

| # | Item | Detalhe | Estado |
|---|---|---|---|
| P4.1 | **Cargo Workspace** | `crates/pinterest-core` e `crates/pinterest-cli` | ✅ |
| P4.2 | **Token Bucket Rate Limiter** | controle de taxa thread-safe com Tokio e exponential backoff | ✅ |
| P4.3 | **Fast HTML/JSON Parser** | extração de pins via `__PWS_DATA__` e meta tags `og:image` | ✅ |
| P4.4 | **Async Stream Downloader** | streams de download `reqwest` com semáforos assíncronos | ✅ |
| P4.5 | **CLI Nativa** | interface de comando moderna (`clap`) com barras visuais (`indicatif`) | ✅ |
| P4.6 | **Testes Unitários Rust** | suíte nativa em `cargo test` validada | ✅ |
| P4.7 | **Branch & Pull Request** | branch `feat/rust-core` criada, PR #11 aberto para `main` | ✅ |

---

## Documentos Relacionados

- [`PROJECT.md`](PROJECT.md)
- [`TEST_INFRA.md`](TEST_INFRA.md)
- [`HANDOFF.md`](HANDOFF.md)
