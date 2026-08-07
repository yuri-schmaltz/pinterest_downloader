# app-pinterest-dl

Ferramenta para baixar imagens de quadros do Pinterest, disponível em três sabores:

- 🐍 **CLI Python** — script de linha de comando para uso em scripts e servidores.
- 🖼️ **GUI PyQt6** — interface desktop com seleção visual de quadros e progresso.
- 🌐 **Chrome extension (MV3)** — extensão do navegador que baixa com um clique direto da página do Pinterest.

Todos os três compartilham o mesmo objetivo (baixar boards públicos) mas têm **caminhos de uso independentes** — escolha o que cabe no seu fluxo.

## ✨ Recursos

- Download de um quadro específico ou de todos os quadros públicos de um usuário.
- Resolução automática da melhor imagem disponível para cada pin.
- Execução paralela configurável para acelerar a coleta e o download.
- Suporte a login manual quando necessário (quadro privado/somente logados).
- **🚀 Cache inteligente** (80-90% cache hits, -70% tempo em re-downloads)
- **⚙️ Adaptive Workers** (ajuste dinâmico de paralelismo baseado em CPU/RAM)
- **🚦 Rate Limiting** (proteção contra HTTP 429, <1% de erros)
- **📝 JSON Logging** (logs estruturados com timestamps para análise)
- **🤖 CI/CD** (testes automatizados no GitHub Actions em 3.10/3.11/3.12)

## Requisitos

- Python 3.10+
- [Playwright](https://playwright.dev/python/) + Chromium (`playwright install chromium`)
- Dependências listadas em `requirements.txt`

## Instalação

```bash
# 1. Clonar e entrar
git clone https://github.com/yuri-schmaltz/pinterest_downloader.git
cd pinterest_downloader

# 2. (Recomendado) Ambiente virtual
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell

# 3. Dependências
pip install -r requirements.txt
playwright install chromium

# 4. (Opcional) Modo editável — expõe os comandos `pinterest-board-dl` e `pinterest-board-gui`
pip install -e .
```

> **Dica:** em ambientes sem interface gráfica disponível, utilize a flag `--headful` apenas quando realmente precisar depurar/login.

## Estrutura do repositório

```
.
├── src/                          # Backend Python
│   ├── pinterest_board_dl.py     #   CLI + scraper com Playwright (1519 LOC)
│   ├── pinterest_board_gui.py    #   GUI PyQt6 (843 LOC)
│   ├── adaptive_workers.py       #   ONDA 5C — ajuste dinâmico de paralelismo
│   ├── rate_limiter.py           #   ONDA 5E — proteção contra 429
│   └── json_logger.py            #   ONDA 5B — logs estruturados
│
├── extension/                    # Chrome extension (MV3)
│   ├── manifest.json             #   Host: pinterest.com, permissions mínimas
│   ├── lib/utils.js              #   Helpers compartilhados (PINTEREST_BASE_URL, etc.)
│   ├── content/content.js        #   Injetado em páginas Pinterest (XHR interception)
│   ├── background/service-worker.js  #   Fila de downloads via chrome.downloads API
│   ├── popup/                    #   UI da extensão (popup.html/css/js)
│   └── icons/                    #   Ícones 16/32/48/128
│
├── tests/                        # Suíte de testes pytest
│
├── docs/                         # Documentação técnica (4K LOC)
│   ├── ONDAS_COMPLETAS.md        #   Resumo das 6 ondas de modernização
│   ├── ONDA_5B/C/D/E_GUIDE.md    #   Guides por onda
│   ├── RUNBOOK_INSTALL.md        #   Install Linux/Windows
│   ├── RUNBOOK_TROUBLESHOOTING.md
│   ├── PERFORMANCE_AUDIT_REPORT.md
│   └── QUICK_REFERENCE.md
│
├── .github/workflows/            # tests.yml (pytest + smoke-import + lint) e release.yml
├── pyproject.toml, requirements.txt
├── assets/icon.svg
├── LICENSE (MIT)
└── README.md
```

## Uso — CLI (linha de comando)

**Modo 1: console script** (após `pip install -e .`):

```bash
pinterest-board-dl https://www.pinterest.com/<usuario>/<quadro>/
```

**Modo 2: módulo direto** (sem instalar em modo editável):

```bash
python -m pinterest_board_dl https://www.pinterest.com/<usuario>/<quadro>/
# ou:
cd src && python pinterest_board_dl.py https://www.pinterest.com/<usuario>/<quadro>/
```

**Baixar todos os quadros públicos de um usuário:**

```bash
pinterest-board-dl --user usuario_pinterest
# ou:
pinterest-board-dl https://www.pinterest.com/usuario_pinterest/
```

**Opções úteis:**

| Flag | Descrição |
|---|---|
| `-o`/`--out` | Pasta de saída (default: `./pins`) |
| `--headful` | Abre o navegador visível durante a coleta |
| `--manual-login` | Pausa para login antes de coletar (perfis privados) |
| `--max-pins N` | Limita a N pins por quadro |
| `--workers N` | Paralelismo interno (resolução/download, default: 16) |
| `--boards-workers N` | Quadros processados em paralelo (default: 1) |
| `--cache-dir DIR` | Diretório do cache de metadados (XDG/AppData por default) |
| `--no-cache` | Desabilita cache de metadados |
| `--adaptive-workers` | Ajusta workers dinamicamente baseado em CPU/RAM (ONDA 5C) |
| `--rate-limiting` | Limitação inteligente de requisições (ONDA 5E) |
| `--json-log` | Habilita logging estruturado em JSON |
| `--log-file PATH` | Arquivo de log JSON (default: `download_log.json`) |

**🚀 Exemplo completo (todas as otimizações):**

```bash
pinterest-board-dl <URL> \
  --workers 32 \
  --adaptive-workers \
  --rate-limiting \
  --json-log \
  --log-file my_download.json
```

## Uso — GUI (interface desktop)

**Modo 1: console script** (após `pip install -e .`):

```bash
pinterest-board-gui
```

**Modo 2: módulo direto:**

```bash
python -m pinterest_board_gui
# ou:
cd src && python pinterest_board_gui.py
```

A janela principal possui:

1. **Aba "Quadro único"** — informe a URL completa do quadro a baixar.
2. **Aba "Todos os quadros do usuário"** — informe o usuário ou URL do perfil.

Configure workers, pausa entre scrolls e login manual na seção "Opções de download" e clique em **Iniciar download**. O painel de progresso mostra o andamento do quadro atual, o total de quadros e o histórico. O log detalhado exibe mensagens e avisos.

O botão **Cancelar** solicita o término do processo atual de forma segura.

> **Nota:** as flags `--adaptive-workers` e `--rate-limiting` estão disponíveis na CLI. A GUI ainda não as expõe (PR aberto no backlog).

## Uso — Chrome extension 🌐

A extensão roda 100% no browser usando a `chrome.downloads` API — não precisa de Python nem Playwright.

**Install (modo developer):**

1. Abra `chrome://extensions/` (ou `edge://extensions/`, `brave://extensions/`)
2. Ative o **Modo desenvolvedor** (toggle no canto superior direito)
3. Clique em **Carregar sem compactação** e selecione a pasta `extension/` deste repositório
4. O ícone do Pinterest Board Downloader aparece na barra de extensões

**Uso:**

1. Navegue para um board do Pinterest (`https://www.pinterest.com/usuario/board/`)
2. Clique no ícone da extensão
3. Popup detecta automaticamente o tipo de página:
   - **Perfil** (`/usuario/`) → botão "Listar Quadros" mostra todos os boards com thumbnails e contagem
   - **Board** (`/usuario/board/`) → botão "Baixar Esta Página" baixa direto
4. Selecione os boards desejados e clique em **Baixar**
5. Arquivos vão para `Pinterest/<usuario>/<board>/` na sua pasta de Downloads

**Como funciona tecnicamente:**

- Content script é injetado em `*.pinterest.com/*` no load
- Intercepta responses de XHR/fetch (`BoardFeedResource`, `UserPinsResource`, `BoardResource`, GraphQL) para extrair URLs de imagem em background (sem scrape HTML)
- Service worker (MV3) gerencia fila com `MAX_CONCURRENT=6` downloads via `chrome.downloads` API
- Cache de pin → image URL fica em `chrome.storage.local` (não persiste entre browsers, mas é instantâneo)

**Permissions necessárias** (declaradas no `manifest.json`):

- `downloads` — escrever arquivos no disco via API do browser
- `activeTab` — acessar a URL atual quando você clica no ícone
- `storage` — cache de metadados
- `scripting` — injetar content script sob demanda
- `host_permissions: *://*.pinterest.com/*` — rodar scripts só no Pinterest

## Desenvolvimento

- **Estrutura:** `src/` contém toda a lógica Python (Playwright + requests); `extension/` é a Chrome extension standalone. Os dois produtos são **independentes** — não compartilham código, mas compartilham o mesmo `git tag` por versionamento unificado.
- **Funções reutilizáveis:** `pinterest_board_dl` expõe `download_board`, `download_user_boards`, `collect_board_urls`, `resolve_images` — integráveis em outros projetos.
- **Testes:** `pytest tests/` (CI roda em Python 3.10/3.11/3.12 via GitHub Actions)
- **Linting:** `ruff check src/ tests/` + `black --check src/ tests/` + `mypy src/`
- **Smoke import gate:** CI valida que todos os símbolos públicos do package importam corretamente (proteção contra regressões de `ImportError`)

## 📚 Documentação Completa

### Guias de Uso
- **[RUNBOOK_INSTALL.md](docs/RUNBOOK_INSTALL.md)** — Instalação detalhada Linux/Windows
- **[RUNBOOK_TROUBLESHOOTING.md](docs/RUNBOOK_TROUBLESHOOTING.md)** — Resolução de problemas comuns

### Guias Técnicos
- **[IMPLEMENTATION_SUMMARY.md](docs/IMPLEMENTATION_SUMMARY.md)** — Resumo técnico de todas as implementações
- **[ONDAS_COMPLETAS.md](docs/ONDAS_COMPLETAS.md)** — Resumo visual das 6 ondas de modernização
- **[ONDA_5B_GUIDE.md](docs/ONDA_5B_GUIDE.md)** — JSON logging com exemplos jq
- **[ONDA_5C_GUIDE.md](docs/ONDA_5C_GUIDE.md)** — Adaptive workers e métricas
- **[ONDA_5D_GUIDE.md](docs/ONDA_5D_GUIDE.md)** — CI/CD e benchmarks
- **[ONDA_5E_GUIDE.md](docs/ONDA_5E_GUIDE.md)** — Rate limiting e proteção 429
- **[PERFORMANCE_AUDIT_REPORT.md](docs/PERFORMANCE_AUDIT_REPORT.md)** — Audit de performance completo
- **[QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)** — Cheat sheet de uso

## 📊 Performance

| Métrica | Antes | Depois | Ganho |
|---------|-------|--------|-------|
| Startup (multi-board) | 15s/board | <1s/board | **93%** ⚡ |
| Cache hits | 0% | 80-90% | **90%** 💾 |
| CPU utilization | 25% | 70-90% | **180%** 🚀 |
| 429 errors | 15% | <1% | **93%** 🛡️ |

## License

MIT — veja [LICENSE](LICENSE).

Contribuições são bem-vindas!
