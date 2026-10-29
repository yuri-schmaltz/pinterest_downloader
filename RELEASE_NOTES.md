## O que há de novo na v2.0.5

Esta release traz a **nova interface gráfica (GUI)** redesenhada em três
etapas, suporte a **tema escuro moderno**, miniaturas quadradas com
letterbox e melhorias fundamentais de compatibilidade e scraper.

### Nova Interface Gráfica (GUI) em Três Etapas
- **Fluxo guiado:** Busca de usuário e listagem -> Seleção visual de quadros -> Acompanhamento e download.
- **Tema escuro integrado:** Interface polida com contraste aprimorado e perfis/estatísticas sempre visíveis.
- **Miniaturas quadradas:** Tratamento consistente de capas e cards de quadros.

### CLI e Scraper
- Novas flags de linha de comando: --version e --user suportadas nativamente.
- Refatoração de modularidade no scraper: extração de handle_response e esolve_images.
- Compatibilidade multiplataforma refinada: suporte a ambientes Windows (resolução de UTF-8 em leituras e precisão de timers de log com 	ime.perf_counter).

### Cobertura e Confiabilidade
- Suíte expandida para **198 testes automatizados** em Python (100% PASS).
- Cobertura global atingindo **60%** (GUI com **72%** e Rate Limiter com **86%**).

---

## O que há de novo na v2.0.4

Esta é a **primeira release com testes de verdade**. A v2.0.1 e a v2.0.2
publicavam um app que ninguém testava; a v2.0.3 consertou o build, mas o
código continuava sem cobertura. Agora o scraper, a GUI e a extensão têm
testes que rodam a cada push.

### A extensão foi consertada

As funções que decidem **qual imagem o usuário baixa** estavam trancadas
dentro de uma função anônima em `content.js` — inalcançáveis de qualquer
teste, que é justamente onde mora o tipo de bug que o usuário vê. Foram
extraídas para `extension/lib/pin_utils.js`, carregado antes do `content.js`
pelo manifest, como o `lib/i18n.js`.

Se você usa a extensão, **atualize**: o pacote da v2.0.3 não tinha esse
arquivo.

### Três bugs reais corrigidos

| | O que acontecia |
|---|---|
| **Títulos dos quadros** | a GUI não colapsava espaços repetidos, embora o comentário do código dissesse que fazia |
| **Pacote da extensão** | `zip -r` *atualiza* um arquivo existente em vez de recriá-lo — um arquivo apagado da extensão continuava no pacote publicado, para sempre |
| **Imports quebrados na CI** | os testes da GUI quebravam em todas as versões do Python por falta de `libEGL.so.1` no runner do GitHub |

### Cobertura: 23 % → 45 %

| Módulo | Antes | Agora |
|---|---|---|
| GUI | **0 %** | **61 %** |
| Scraper | 16 % | **21 %** |
| **Total** | 23 % | **45 %** |

De 21 para **85 testes** em Python, mais **69 verificações** da extensão.
O scraper passa a ser testado num Chromium real, contra fixtures HTML
locais — sem rede. A GUI é testada em modo `offscreen`, sem display.

### A versão agora tem uma fonte só

A versão vivia em três lugares independentes e divergia — a v2.0.1
publicou arquivos com o nome `v2.0.0`. Agora o `manifest.json` é a fonte
da verdade, o `scripts/sync_version.py` sincroniza o `pyproject.toml`, e a
CI **falha o build** se eles discordarem ou se a tag não bater.

### Documentação

- `extension/README.md` — a extensão não tinha doc própria
- `README.md`, `PROJECT.md`, `PLANO-ESTABILIZACAO.md`, `TEST_INFRA.md` —
  reescritos para descrever o que o código **realmente** faz
- `docs/RUNBOOK_INSTALL.md`, `docs/RUNBOOK_TROUBLESHOOTING.md`,
  `docs/QUICK_REFERENCE.md` — instalação, diagnóstico e referência rápida
- `scripts/diagnose.py` — diagnóstico do ambiente, 100 % offline

---

<details>
<summary>⚠️ O que os testes ainda <b>não</b> garantem</summary>

A suíte grew rápido, mas vale ser honesto sobre os limites — estão
declarados em `TEST_INFRA.md` §6:

- **Nenhum teste toca a rede.** As fixtures de HTML são sintéticas: se o
  Pinterest mudar o layout de verdade, nenhum teste avisa.
- **O download real não é testado.** Nenhum teste baixa um arquivo e confere
  o que foi salvo.
- **A extensão não é testada carregada de verdade.** Os scripts são
  injetados à mão, o `chrome.*` não é real.
- **O caminho de popups, lazy-load e login manual** contra o Pinterest de
  verdade segue sem cobertura.

</details>
