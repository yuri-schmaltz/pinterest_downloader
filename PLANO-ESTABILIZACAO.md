# PLANO-ESTABILIZACAO.md

**Data:** 2026-10-22 · **Estado atual:** v2.0.0 na `main`, branch de estabilização com 9 commits
**Referência:** [`PROJECT.md`](PROJECT.md) · [`TEST_INFRA.md`](TEST_INFRA.md)

---

## Situação

A `main` estava com **tudo vermelho desde 2026-02-07**: CI falhando em
todos os pushes, suíte coletando 0 testes, extensão não reproduzível a
partir do repositório, e release quebrada em 3 tags seguidas. O código em si
era razoável — o problema era o entorno.

O que já foi resolvido está na branch `fix/ci-and-extension-repro`:

| # | Entrega | Estado |
|---|---|---|
| 1 | `extension/lib/i18n.js` versionado + whitelist `!extension/lib/` | ✅ |
| 2 | Suíte volta a rodar (0 → 21 testes) | ✅ |
| 3 | `tests/test_playwright.py` → `scripts/debug_pinterest.py` | ✅ |
| 4 | `tests.yml` reescrito, 4 jobs bloqueantes | ✅ |
| 5 | `release.yml` corrigido + `PinterestDownloader.spec` criado e build verificado | ✅ |
| 6 | `pip install .` passa a instalar de verdade + console scripts | ✅ |
| 7 | Lint com black/ruff/mypy sem `\|\| true` | ✅ |
| 8 | `scripts/diagnose.py` (diagnóstico offline) | ✅ |

---

## P0 — Bloqueia release

> **✅ P0 entregue em 2026-10-23.** A `v2.0.4` foi publicada com 6 artefatos
> verificados, buildados a partir da `main`. Os itens abaixo ficam como
> registro do que era o bloqueio.

Sem isso não dá para publicar nada confiável.

| # | Item | Por que é P0 | Esforço | Estado |
|---|---|---|---|---|
| P0.1 | **Merge da branch de estabilização** | contém os fixes; nada disso chega à `main` sem merge | 10 min | ✅ PR #10 mergeado, CI verde na `main` |
| P0.2 | **Fechar os 7 PRs antigos** | abertos há 2,5 meses, baseados na arquitetura v1 | 30 min | ✅ feito, com justificativa em cada |
| P0.3 | **Gerar e publicar `v2.0.3`** | as três tags anteriores não tinham artefato válido | 1 h | ✅ publicada e depois removida (a extensão nela estava defasada) |
| P0.4 | **Subir a versão para 2.0.3** | `pyproject.toml` e `extension/manifest.json` precisam concordar | 15 min | ✅ ambos em 2.0.3 |
| P0.5 | **Publicar a `v2.0.4`** | a `v2.0.3` não tem `lib/pin_utils.js` nem os testes | 1 h | ✅ 6 artefatos, verificados, tagueada na `main` |

### P0.3 — critérios de aceite da release

- [x] `v2.0.3` no `pyproject.toml` **e** no `extension/manifest.json`
- [x] tag `v2.0.3` criada e workflow disparada
- [x] `v2.0.4` no `pyproject.toml` **e** no `extension/manifest.json`
- [x] tag `v2.0.4` criada, workflow disparada e 6 artefatos verificados
- [x] AppImage gerado (379 MB) **e verificado** (contém o executável e o Chromium; app sobe)
- [x] `.deb` gerado (339 MB)
- [x] zip Windows gerado (424 MB) — a árvore onedir completa, não só o `.exe`
- [x] zip Chrome **contém** `lib/i18n.js` (conferido baixando o asset publicado)
- [x] source tarball **contém** `src/` e `tests/` (conferido baixando o asset publicado)
- [x] release notes descrevendo as correções

### P0.5 — restante do P0

| # | Item | Esforço | Estado |
|---|---|---|---|
| P0.5 | **Mergear o PR #10** na `main` — é o que falta para a `main` receber as correções | 5 min | ✅ mergeado (`ef042b0`) |
| P0.6 | **Deletar o draft da `v2.0.2`**, que ficou com 3 assets órfãos e nunca foi publicado | 2 min | ✅ deletado |
| P0.7 | **Publicar a `v2.0.4` buildada a partir da `main`** | 30 min | ✅ 6 assets verificados |
| P0.8 | **Deletar o release da `v2.0.3`**, cuja extensão estava sem o `lib/pin_utils.js` | 5 min | ✅ deletado (a tag ficou, para o link de changelog) |

---

## P1 — Dívida que incomoda

| # | Item | Detalhe | Esforço | Estado |
|---|---|---|---|---|
| P1.1 | **Reescrever o README** | hoje descreve o layout pré-`src/`, manda rodar `python pinterest_board_dl.py` (agora é `src/`), cita `diagnostics.py` e `benchmark.py` (inexistentes) e afirma "11 testes, 100 % PASS" (são 21) | 2 h | ✅ |
| P1.2 | **Sanear `docs/`** | 10 arquivos, 8 deles citando arquivos deletados. Os 5 guias "ONDA" são histórico — precisam de banner, não de reescrita. `RUNBOOK_INSTALL`, `RUNBOOK_TROUBLESHOOTING` e `QUICK_REFERENCE` são **operacionais** e precisam estar certos | 3 h | ✅ |
| P1.3 | **Deduplicar as dependências** | `requirements.txt` e `pyproject.toml` listam as mesmas 4 dependências. Duas fontes de verdade, uma delas não entra no wheel | 20 min | ✅ `requirements-dev.txt` adicionado |
| P1.4 | **Unificar a versão** | hoje 3 lugares: `pyproject.toml`, `extension/manifest.json` e a tag. Automatizar: o `build_release.sh` já deriva do manifest; falta o pyproject seguir o mesmo caminho | 1 h | ✅ resolvido pelo P1.7 |
| P1.5 | **Fechar o gap de `lib/` no `.gitignore`** | a regra `lib/` continua lá, protegida só pela whitelist. Um `.gitignore` que aponte apenas para o que é Python evitaria a classe de bug inteira | 30 min | ✅ whitelist + gate de CI |
| P1.6 | **`extension/README.md`** | removido no restructure v2, mas a extensão segue sem doc própria | 1 h | ✅ escrito, com checklist de publicação |
| P1.7 | **Unificar a versão** | 3 fontes: pyproject, manifest, tag. A v2.0.1 publicou assets nomeados `v2.0.0` | 1 h | ✅ `scripts/sync_version.py` + job `version` no CI. Agora com **3 cópias derivadas** (pyproject, `src/_version.py`, tag), todas conferidas contra o manifest |

---

## P2 — Qualidade

| # | Item | Detalhe | Esforço |
|---|---|---|---|
| P2.1 | **Cobertura do scraper (16 % → 21 %)** | fixtures de HTML local + Chromium real: coleta de pins e extração de quadros | ✅ feito (falta HTML real capturado) |
| P2.2 | **Testes da GUI (0 % → 61 %)** | `pytest-qt` + platform `offscreen`, sem `xvfb` | ✅ feito (falta o ciclo de download) |
| P2.3 | **Testes da extensão** | a extensão não tinha nenhum teste | ✅ 82 checks em Node + 13 de integração |
| P2.4 | **Refatorar as 8 funções complexas** | `C901` está no ignore do ruff. A mais complexa tinha 63; a extração do scroll-stability já a levou a 60 | 2–3 dias | 🟡 **parcial**: `handle_response` (25) e `resolve_images` (16) extraídos e agora testados. Restam 5 funções acima de 15: `_collect_pin_links_with_browser` (37), `collect_board_urls` (22), `download_board` (20), `_collect_with_page` (19), `_status_callback` (16) |
| P2.5 | **Benchmark automatizado** | as tabelas de performance nos docs (93 %, 90 %, 180 %) são de medições manuais de 2025 e não são reproduzíveis | 1 dia |
| P2.6 | **`--version` na CLI** | o runbook antigo mandava `python pinterest_board_dl.py --version`, mas a flag não existe | 15 min | ✅ `src/app_version.py` + `src/_version.py` gerado |
| P2.7 | **`--user` na CLI** | o README e 5 guias "ONDA" usam `pinterest-board-dl --user NOME`, mas a flag não existia — o comando falhava com "unrecognized arguments" | 15 min | ✅ flag criada (o posicional continua funcionando) |
| P2.8 | **Parser da CLI separado do `main()`** | o `main()` abria o navegador, o que impedia testar o parse sem tocar a rede | 15 min | ✅ `build_arg_parser()` |

---

## P3 — Bônus / nice to have

| # | Item | Detalhe |
|---|---|---|
| P3.1 | Publicar a extensão no Chrome Web Store | `scripts/publish_chrome.py` existe e está pronto, mas exige credenciais OAuth2 do Google |
| P3.2 | Assinar o XPI para o Firefox Add-ons | a Mozilla exige assinatura; hoje o `.xpi` é publicado sem assinar |
| P3.3 | BUILD do Windows com o Chromium embutido | o job do Windows não baixa o Chromium; o app Windows vai exigir `playwright install chromium` |
| P3.4 | Cross-compilar .deb para arm64 | hoje só amd64 |
| P3.5 | Badge de CI no README | assim que o CI estiver verde de forma estável | ✅ badge de CI + badge de release |

---

## Ordem sugerida

```
P0.1 merge da branch        ✅
  → P0.2 fechar os 7 PRs superseded   ✅
    → P0.4 subir versão               ✅
      → P0.3 publicar a release        ✅ v2.0.3 (removida depois)
        → P1.1 README + P1.2 docs     ✅
          → P1.3 / P1.4 / P1.5 / P1.6 / P1.7   ✅
            → P2.1 / P2.2 / P2.3 / P2.6 / P2.7 / P2.8   ✅
              → P0.7 v2.0.4 buildada da main           ✅
                → P2.4 (parcial) / P2.5 / P3.x
```

**Estimativa:** P0 inteiro em ~2 h. P1 inteiro em ~1 dia. P2 é a partir daí.

**Bloqueio atual (2026-10-29):** os três tokens do GitHub no ambiente
(`GITHUB_TOKEN`, `GITHUB_PUSH_TOKEN`, `GITHUB_PAT`) respondem **401 Bad
credentials**. Sem escrita remota não dá para deletar a branch já
mergeada `fix/ci-and-extension-repro` nem as releases antigas
`v2.0.0`/`v2.0.1` (cujo source tarball não tinha o código do app). O
trabalho de código continua normal.

---

## Riscos

| Risco | Mitigação |
|---|---|
| O `PinterestDownloader.spec` foi verificado no Linux **e** no Windows | os dois jobs de build passaram na `v2.0.3`; o AppImage foi verificado por extração (contém o executável e o Chromium) |
| O AppImage com Chromium embutido tem ~379 MB (o bundle onedir tem 954 MB antes de compactar) | Considerar AppImage sem Chromium (usando o do sistema) se o tamanho incomodar |
| A extensão nunca foi testada automaticamente **em comportamento** | Resolvido: 69 checks em Node + 13 testes de integração num Chromium real. Ainda falta o `chrome.*` de verdade (a extensão carregada, não injetada) |
| A suíte cobre 50 % do código (o scraper, 32 %) | Não confie na suíte como rede de segurança para o scraper. Mudanças no scraper exigem teste manual com um quadro real |
| O `.deb` e o zip do Windows não foram instalados de fato num sistema limpo | O `.deb` foi gerado e inspecionado; o app foi testado subindo headless a partir do bundle. Falta instalar numa VM |
