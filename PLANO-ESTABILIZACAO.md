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

Sem isso não dá para publicar nada confiável.

| # | Item | Por que é P0 | Esforço |
|---|---|---|---|
| P0.1 | **Merge da branch de estabilização** | contém os 9 fixes; nada disso chega à `main` sem merge | 10 min |
| P0.2 | **Fechar os 7 PRs antigos** | estão abertos há 2,5 meses, baseados na arquitetura v1, e confundem qualquer revisão futura. 6 são **supersedidos** pela branch; 1 (`chore/sync-extension-version`) faz *downgrade* do manifest v2 para o v1 | 30 min |
| P0.3 | **Gerar e publicar `v2.0.3`** | as três tags anteriores (`v2.0.0`, `v2.0.1`, `v2.0.2`) não têm artefato válido. Sem uma release boa, o projeto continua sem distribuição | 1 h |
| P0.4 | **Subir a versão para 2.0.3 em todo lugar** | `pyproject.toml`, `extension/manifest.json` e a tag precisam concordar — hoje o `build_release.sh` deriva a versão do manifest, mas o pyproject é manual | 15 min |

### P0.3 — critérios de aceite da release

- [ ] `v2.0.3` no `pyproject.toml` **e** no `extension/manifest.json`
- [ ] tag `v2.0.3` criada e workflow disparada
- [ ] AppImage gerado **e** testado (subir headless)
- [ ] `.deb` gerado e `dpkg -i` testado
- [ ] `.exe` do Windows gerado
- [ ] zip Chrome **contém** `lib/i18n.js` (conferir com `unzip -l`)
- [ ] source tarball **contém** `src/` e `tests/`
- [ ] release notes descrevendo as correções

---

## P1 — Dívida que incomoda

| # | Item | Detalhe | Esforço |
|---|---|---|---|
| P1.1 | **Reescrever o README** | hoje descreve o layout pré-`src/`, manda rodar `python pinterest_board_dl.py` (agora é `src/`), cita `diagnostics.py` e `benchmark.py` (inexistentes) e afirma "11 testes, 100 % PASS" (são 21) | 2 h |
| P1.2 | **Sanear `docs/`** | 10 arquivos, 8 deles citando arquivos deletados. Os 5 guias "ONDA" são histórico — precisam de banner, não de reescrita. `RUNBOOK_INSTALL`, `RUNBOOK_TROUBLESHOOTING` e `QUICK_REFERENCE` são **operacionais** e precisam estar certos | 3 h |
| P1.3 | **Deduplicar as dependências** | `requirements.txt` e `pyproject.toml` listam as mesmas 4 dependências. Duas fontes de verdade, uma delas não entra no wheel | 20 min |
| P1.4 | **Unificar a versão** | hoje 3 lugares: `pyproject.toml`, `extension/manifest.json` e a tag. Automatizar: o `build_release.sh` já deriva do manifest; falta o pyproject seguir o mesmo caminho | 1 h |
| P1.5 | **Fechar o gap de `lib/` no `.gitignore`** | a regra `lib/` continua lá, protegida só pela whitelist. Um `.gitignore` que aponte apenas para o que é Python evitaria a classe de bug inteira | 30 min |
| P1.6 | **`extension/README.md`** | removido no restructure v2, mas a extensão segue sem doc própria | 1 h |

---

## P2 — Qualidade

| # | Item | Detalhe | Esforço |
|---|---|---|---|
| P2.1 | **Cobertura do scraper (16 % → 50 %)** | fixtures de HTML salvo do Pinterest; cobre scroll, parsing, popups sem depender de rede | 1–2 dias |
| P2.2 | **Testes da GUI (0 % → 30 %)** | `pytest-qt` + `xvfb` | 2–3 dias |
| P2.3 | **Testes da extensão** | a extensão não tem nenhum teste; jsdom ou Playwright com extensão carregada | 1–2 dias |
| P2.4 | **Refatorar as 8 funções complexas** | `C901` está no ignore do ruff. A mais complexa (`_collect_pin_links_with_browser`) tem complexidade 63. Extrair o scroll-stability para um módulo próprio é o corte natural | 2–3 dias |
| P2.5 | **Benchmark automatizado** | as tabelas de performance nos docs (93 %, 90 %, 180 %) são de medições manuais de 2025 e não são reproduzíveis | 1 dia |
| P2.6 | **`--version` na CLI** | o runbook antigo mandava `python pinterest_board_dl.py --version`, mas a flag não existe | 15 min |

---

## P3 — Bônus / nice to have

| # | Item | Detalhe |
|---|---|---|
| P3.1 | Publicar a extensão no Chrome Web Store | `scripts/publish_chrome.py` existe e está pronto, mas exige credenciais OAuth2 do Google |
| P3.2 | Assinar o XPI para o Firefox Add-ons | a Mozilla exige assinatura; hoje o `.xpi` é publicado sem assinar |
| P3.3 | BUILD do Windows com o Chromium embutido | o job do Windows não baixa o Chromium; o app Windows vai exigir `playwright install chromium` |
| P3.4 | Cross-compilar .deb para arm64 | hoje só amd64 |
| P3.5 | Badge de CI no README | assim que o CI estiver verde de forma estável |

---

## Ordem sugerida

```
P0.1 merge da branch
  → P0.2 fechar os 7 PRs superseded
    → P0.4 subir versão para 2.0.3
      → P0.3 gerar e publicar a release v2.0.3
        → P1.1 README + P1.2 docs (com a release viva, os docs podem citar a versão real)
          → P1.3 / P1.4 / P1.5 / P1.6
            → P2.x
```

**Estimativa:** P0 inteiro em ~2 h. P1 inteiro em ~1 dia. P2 é a partir daí.

---

## Riscos

| Risco | Mitigação |
|---|---|
| O `PinterestDownloader.spec` foi verificado **no Linux**; o job do Windows nunca rodou com o spec novo | O primeiro build de `v2.0.3` expõe isso. Se o Windows falhar, publicar a release só com os artefatos Linux e investigar à parte |
| O AppImage com Chromium embutido tem ~950 MB | Considerar AppImage sem Chromium (usando o do sistema) se o tamanho incomodar |
| A extensão nunca foi testada automaticamente | O job `extension` valida a integridade do pacote, mas não o comportamento. Uma mudança no layout do Pinterest quebra a extensão sem aviso |
| A suíte cobre 23 % do código | Não confie na suíte como rede de segurança para o scraper. Mudanças no scraper exigem teste manual com um quadro real |
