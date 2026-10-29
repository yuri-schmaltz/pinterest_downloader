# Pinterest Pro Downloader

[![Tests & Quality](https://github.com/yuri-schmaltz/pinterest_downloader/actions/workflows/tests.yml/badge.svg)](https://github.com/yuri-schmaltz/pinterest_downloader/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/yuri-schmaltz/pinterest_downloader.svg)](https://github.com/yuri-schmaltz/pinterest_downloader/releases/latest)

Baixa imagens de quadros do Pinterest com máxima velocidade, resiliência e integridade.

O projeto disponibiliza **quatro vertentes independentes**:

- 🦀 **Rust Core & CLI (Novo em v2.0.5 / PR #11)** — binário nativo compilado, ultra-rápido, assíncrono com Tokio, stream download e rate-limiter Token Bucket.
- 🐍 **Python CLI** — linha de comando completa (`pinterest-board-dl`), scriptável com Playwright e requests.
- 🖼️ **GUI Moderna (PyQt6)** — desktop em tema escuro e fluxo guiado de 3 etapas (*Perfil → Escolher quadros → Baixar*).
- 🌐 **Extensão de Navegador** — Chrome (MV3) e Firefox (XPI), JavaScript puro sem dependência de interpretadores locais.

---

## ✨ Recursos

- **Download em Alta Performance:** Paralelismo adaptativo ajustado por CPU/RAM (`--adaptive-workers`).
- **Resolução Automática:** Detecção da URL em resolução original (`orig`), `736x` ou `474x`.
- **Proteção Ativa:** Rate limiter com Token Bucket e backoff exponencial contra HTTP 429.
- **Cache Inteligente:** Re-download quase instantâneo com verificação de metadados no disco.
- **Detecção de Perfis Privados:** Orientação clara e suporte a login manual interativo.
- **Logging Estruturado:** Exportação de métricas e fases em JSON (`--json-log`).
- **Compatibilidade Multiplataforma Real:** Linux, Windows e macOS (suporte a UTF-8 e timers precisos via `time.perf_counter`).

---

## 🦀 Usando a versão em Rust puro (Alta Performance)

O workspace Rust em `crates/` fornece uma CLI compilada independente de interpretador:

```bash
# Compilar binário release
cargo build --release

# Executar a CLI em Rust
./target/release/pinterest-cli --help

# Baixar quadro com 16 workers
./target/release/pinterest-cli https://www.pinterest.com/usuario/quadro/ -w 16
```

---

## 🐍 Instalação e Uso — Python (CLI e GUI)

### Requisitos
- Python ≥ 3.10
- [Playwright](https://playwright.dev/python/) com Chromium instalado

```bash
# 1. Clone o repositório
git clone https://github.com/yuri-schmaltz/pinterest_downloader.git
cd pinterest_downloader

# 2. Crie e ative o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .\.venv\Scripts\Activate.ps1  # Windows PowerShell

# 3. Instale as dependências e o Chromium
pip install -e ".[dev]"
python -m playwright install chromium

# 4. Diagnóstico completo de ambiente
python scripts/diagnose.py --deep
```

### CLI Python
```bash
# Baixar um quadro específico
pinterest-board-dl https://www.pinterest.com/usuario/quadro/

# Baixar todos os quadros de um usuário com rate limiter e workers adaptativos
pinterest-board-dl --user usuario_pinterest --adaptive-workers --rate-limiting

# Conferir versão
pinterest-board-dl --version
```

### GUI Desktop (PyQt6)
```bash
pinterest-board-gui
# ou: python src/pinterest_board_gui.py
```
A interface conta com fluxo em 3 etapas guiadas:
1. **Perfil:** Digite o usuário e liste os quadros públicos.
2. **Escolha:** Filtro instantâneo por busca, botão *Selecionar Todos*, capas quadradas sem distorção e opções de pasta/workers.
3. **Download:** Acompanhamento do progresso e log em tempo real.

---

## 🌐 Extensão do Navegador (Chrome / Firefox)

1. Baixe o `.zip` (Chrome) ou `.xpi` (Firefox) na [página de Releases](https://github.com/yuri-schmaltz/pinterest_downloader/releases).
2. **Chrome:** Acesse `chrome://extensions`, ative o *Modo do desenvolvedor* e use *Carregar sem compactação*.
3. **Firefox:** Acesse `about:debugging` e carregue o arquivo como complemento temporário.

---

## 🧪 Qualidade de Código e Testes

O repositório possui suíte de testes unitários e de integração sem dependência de rede externa:

```bash
# Suíte Python completa (202 testes, 100% PASS, 63% cobertura)
python -m pytest tests/ -q

# Testes de unidade dos módulos Rust
cargo test

# Linters e tipagem estática
ruff check src/ tests/ scripts/
black --check src/ tests/ scripts/
mypy src/pinterest_board_dl.py src/app_version.py
```

---

## 📦 Artefatos de Instalação (Release v2.0.5)

| Plataforma | Artefato | Descrição |
|---|---|---|
| **Windows** | `pinterest-board-downloader-x64.zip` | Pacote completo standalone (onedir) |
| **Linux** | `PinterestDownloader-x86_64.AppImage` | Imagem com Chromium e dependências embutidas |
| **Linux (Debian/Ubuntu)** | `pinterest-downloader_amd64.deb` | Pacote Debian instalável via `dpkg -i` |
| **Chrome** | `pinterest-pro-downloader-chrome-v2.0.5.zip` | Extensão MV3 empacotada |
| **Firefox** | `pinterest-pro-downloader-firefox-v2.0.5.xpi` | Extensão WebExtension |
| **Source** | `pinterest-pro-downloader-source-v2.0.5.tar.gz` | Código-fonte verificado com suíte completa |

---

## 📚 Documentação Técnica

- [`PROJECT.md`](PROJECT.md) — Visão do produto, contratos de interface e inventário de funcionalidades.
- [`PLANO-ESTABILIZACAO.md`](PLANO-ESTABILIZACAO.md) — Histórico de correções, auditoria ciclomática e marcos entregues.
- [`TEST_INFRA.md`](TEST_INFRA.md) — Detalhamento da cobertura de testes e fixtures locais.
- [`docs/RUNBOOK_INSTALL.md`](docs/RUNBOOK_INSTALL.md) — Guia de instalação passo a passo.
- [`docs/RUNBOOK_TROUBLESHOOTING.md`](docs/RUNBOOK_TROUBLESHOOTING.md) — Solução de problemas frequentes.
- [`docs/QUICK_REFERENCE.md`](docs/QUICK_REFERENCE.md) — Referência rápida de comandos e flags.

---

## ⚖️ Licença

Distribuído sob licença MIT. Consulte [`LICENSE`](LICENSE) para mais detalhes.
