# Pinterest Pro Downloader

[![Tests & Quality](https://github.com/yuri-schmaltz/pinterest_downloader/actions/workflows/tests.yml/badge.svg)](https://github.com/yuri-schmaltz/pinterest_downloader/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/yuri-schmaltz/pinterest_downloader.svg)](https://github.com/yuri-schmaltz/pinterest_downloader/releases/latest)

Baixa imagens de quadros do Pinterest. Três produtos independentes, mesmo objetivo:

- 🐍 **CLI** — linha de comando, para script e servidor
- 🖼️ **GUI** — desktop PyQt6, em três etapas: perfil → escolher quadros → baixar
- 🌐 **Extensão** — Chrome/Firefox (MV3), baixa o que está visível na página

A CLI e a GUI são Python (Playwright + requests). A extensão é JavaScript
puro e não precisa de Python — são caminhos de uso separados, escolha o que
cabe no seu fluxo.

📄 [PROJECT.md](PROJECT.md) tem o inventário completo, os contratos de
interface e a estrutura. [PLANO-ESTABILIZACAO.md](PLANO-ESTABILIZACAO.md) tem
o que ainda falta.

---

## ✨ Recursos

- Download de um quadro específico ou de todos os quadros públicos de um usuário
- Resolução automática da melhor imagem disponível para cada pin
- Execução paralela configurável
- Suporte a login manual (quadros privados / só para logados)
- 🚀 **Cache inteligente** de metadados — re-download quase instantâneo
- ⚙️ **Adaptive workers** — paralelismo ajustado por CPU/RAM
- 🚦 **Rate limiting** — proteção contra HTTP 429 com backoff exponencial
- 📝 **JSON logging** — logs estruturados para análise

---

## Requisitos

- Python 3.10 ou superior
- [Playwright](https://playwright.dev/python/) + Chromium
- Linux, Windows ou macOS

---

## Instalação

```bash
# 1. Clone
git clone https://github.com/yuri-schmaltz/pinterest_downloader.git
cd pinterest_downloader

# 2. Ambiente virtual (recomendado)
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .\.venv\Scripts\Activate.ps1     # Windows PowerShell

# 3. Dependências
pip install -r requirements.txt
python -m playwright install chromium

# 4. Instalar o projeto (opcional, habilita os comandos pinterest-board-dl / pinterest-board-gui)
pip install -e .
```

Sem o passo 4, use `python src/pinterest_board_dl.py` direto — funciona igual.

### Verificar a instalação

```bash
python scripts/diagnose.py
```

Checa Python, dependências, import dos módulos, presença do Chromium,
permissão de escrita no cache e integridade da extensão — em ~1 segundo,
sem abrir navegador e sem tocar a rede. Use `--deep` para também subir o
Chromium, e `--json` para saída machine-readable.

---

## Uso — CLI

```bash
# um quadro
pinterest-board-dl https://www.pinterest.com/usuario/quadro/

# todos os quadros públicos de um usuário
pinterest-board-dl --user usuario_pinterest

# a versão instalada
pinterest-board-dl --version

# com as otimizações todas
pinterest-board-dl <URL> \
  --workers 32 \
  --adaptive-workers \
  --rate-limiting \
  --json-log \
  --log-file my_download.json
```

| Flag | Efeito |
|---|---|
| `-o, --out DIR` | pasta de saída (default `./pins`) |
| `--user NOME` | baixa todos os quadros públicos do usuário (também aceita o nome como argumento posicional) |
| `--version` | mostra a versão e sai |
| `--max-pins N` | limita a quantidade de pins por quadro |
| `--workers N` | paralelismo de resolução/download (default 16) |
| `--boards-workers N` | paralelismo entre quadros (2–3, cada um abre um Chromium) |
| `--scroll-pause S` | pausa entre rolagens (default 1.2) |
| `--cache-dir DIR` | diretório do cache (default: `~/.cache/pinterest-downloader`) |
| `--no-cache` | desliga o cache de metadados |
| `--adaptive-workers` | ajusta workers por CPU/RAM |
| `--rate-limiting` | ativa proteção contra 429 |
| `--json-log` / `--log-file F` | logging estruturado |
| `--headful` | abre o navegador visível (debug / login) |
| `--manual-login` | pausa para você fazer login antes de coletar |

Lista completa: `pinterest-board-dl --help`.

---

## Uso — GUI

```bash
pinterest-board-gui          # instalado via pip install -e .
# ou
python src/pinterest_board_gui.py
```

A janela é um fluxo de **três etapas**, com a barra do topo mostrando onde
você está:

| Etapa | O que tem na tela |
|---|---|
| **1 · Perfil** | campo de usuário/URL e o botão *Listar Quadros* |
| **2 · Escolher quadros** | a grade de quadros (miniatura, título e contagem de pins), a busca, o *Selecionar Todos* e uma faixa de opções (destino, workers, máximo de pins) |
| **3 · Baixar** | o progresso (quadro atual e total de quadros) e o log detalhado |

O campo do perfil fica **na barra do topo**, então continua visível em
todas as etapas — dá para ver o que está sendo baixado sem voltar. Dar
Enter no campo refaz a busca.

Fluxo: informo o usuário → *Listar Quadros* → marco os quadros →
*Iniciar download*. O botão *← Voltar* volta uma etapa; as etapas 1 e 2
também são clicáveis na barra do topo.

A janela é **escura** — não há tema claro.

A busca filtra a grade conforme você digita, e o *Selecionar Todos* marca
só o que está visível na busca. As miniaturas são **quadradas**: a capa do
quadro cabe inteira no quadrado, sem distorcer a proporção da foto. O modo "quadro único" (uma URL de quadro
direto) existe **apenas na CLI**.

> Em máquina sem display, a GUI não abre. O modo `offscreen` existe para
> testes: `QT_QPA_PLATFORM=offscreen python src/pinterest_board_gui.py`.

---

## Uso — extensão do navegador

1. Baixe o `.zip` da página de releases (ou o `.xpi` para Firefox)
2. Chrome: `chrome://extensions` → **Modo do desenvolvedor** → **Carregar
   sem compactação** → selecione a pasta descompactada
3. Firefox: about:debugging → **Extensão temporária** → carregar o `.xpi`

A extensão injeta um botão flutuante na página do Pinterest; um clique
rola a página, coleta as imagens e baixa as melhores resoluções.

A extensão usa i18n (`en`, `es`, `pt_BR`). O `lib/i18n.js` é carregado
**antes** do `content.js` — a ordem no manifest importa.

---

## Desenvolvimento

```bash
# suíte
python -m pytest tests/ -v

# lint (o mesmo do CI)
black --check --line-length 120 src/ tests/ scripts/
ruff check src/ tests/ scripts/
mypy src/pinterest_board_dl.py --ignore-missing-imports

# cobertura
python -m coverage run --source=src -m pytest tests/ -q
python -m coverage report -m

# diagnóstico do ambiente
python scripts/diagnose.py --deep

# empacotar a extensão
bash scripts/build_release.sh

# build do app desktop (precisa do Chromium no bundle)
PLAYWRIGHT_BROWSERS_PATH=~/.cache/ms-playwright \
  pyinstaller --noconfirm --clean PinterestDownloader.spec
```

### Estrutura

```
src/          aplicação Python (módulos soltos — flat imports)
extension/    extensão MV3
tests/        21 testes
scripts/      diagnóstico, build, publicação
docs/         runbooks e histórico
```

Os módulos em `src/` importam uns aos outros de forma "plana"
(`from json_logger import ...`), então `src/` precisa estar no `sys.path`.
Os testes cuidam disso em três lugares — `tests/conftest.py`,
`pythonpath` no `pyproject.toml` e o `sys.path.insert` de cada arquivo.
Se você criar um teste novo, **repita o `sys.path.insert`**: foi
justamente essa migração para `src/` que zerou a suíte inteira.

---

## Instaladores

| Plataforma | Arquivo | Como instalar |
|---|---|---|
| Linux | `PinterestDownloader-x86_64.AppImage` | `chmod +x` e executar |
| Linux | `pinterest-downloader_amd64.deb` | `sudo dpkg -i *.deb` |
| Windows | `pinterest-board-downloader.exe` | executar |
| Chrome | `pinterest-pro-downloader-chrome-*.zip` | carregar sem compactação |
| Firefox | `pinterest-pro-downloader-firefox-*.xpi` | add-on temporário |

O AppImage já traz o Chromium embutido (~950 MB). O `.deb` e o `.exe` **não**
— nesses, rode `python -m playwright install chromium` uma vez.

---

## Documentação

| Documento | Assunto |
|---|---|
| [PROJECT.md](PROJECT.md) | inventário de features, marcos, contratos de interface |
| [PLANO-ESTABILIZACAO.md](PLANO-ESTABILIZACAO.md) | prioridades P0–P3 e riscos |
| [TEST_INFRA.md](TEST_INFRA.md) | cobertura real (23 %) e limites declarados |
| [docs/RUNBOOK_INSTALL.md](docs/RUNBOOK_INSTALL.md) | instalação passo a passo |
| [docs/RUNBOOK_TROUBLESHOOTING.md](docs/RUNBOOK_TROUBLESHOOTING.md) | problemas comuns |
| [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md) | referência rápida de comandos |

---

## Licença

MIT — veja [LICENSE](LICENSE).
