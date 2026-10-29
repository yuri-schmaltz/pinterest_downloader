# 📖 Runbook: Instalação e Configuração

**App:** Pinterest Board Downloader v2.0.3
**Suporte:** Linux (Ubuntu/Debian/Fedora), Windows 10/11, macOS

> Este runbook foi reescrito em 2026-10-22. A versão anterior apontava para
> `python test_patches.py` (arquivo que nunca existiu), `python diagnostics.py`
> (removido no commit `9fb4c3e`) e um clone URL errado (`yurix/my-pinterest-downloader`).

---

## Requisitos

### Hardware mínimo
- **CPU:** dual-core 2.0 GHz
- **RAM:** 4 GB
- **Disco:** 500 MB + espaço para os downloads
- **Rede:** conexão estável

### Software
- Python 3.10 ou superior
- Chromium instalado via Playwright

---

## Instalação

### Linux (Ubuntu/Debian)

```bash
# 1. Clonar
git clone https://github.com/yuri-schmaltz/pinterest_downloader.git
cd pinterest_downloader

# 2. Ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 3. Dependências
pip install -r requirements.txt

# 4. Navegador
python -m playwright install chromium

# 5. Instalar o projeto (opcional: habilita pinterest-board-dl / -gui)
pip install -e .

# 6. Verificar
python scripts/diagnose.py
```

### Linux (Fedora/RHEL)

```bash
sudo dnf install python3-pip python3-virtualenv
# seguir os passos 2 a 6 acima
```

### Linux — servidor sem display

O scraper **não** precisa de display (Playwright roda headless). Só a GUI
precisa. Em servidor, instale as libs de sistema do Chromium:

```bash
sudo apt-get install -y libegl1 libxkbcommon0 libxkbcommon-x11-0 \
    libdbus-1-3 libxcb-icccm4 libxcb-cursor0 libxcb-render-util0
```

### Windows

```powershell
# 1. Clonar (PowerShell ou Git Bash)
git clone https://github.com/yuri-schmaltz/pinterest_downloader.git
cd pinterest_downloader

# 2. Ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Dependências
pip install -r requirements.txt

# 4. Navegador
python -m playwright install chromium

# 5. Instalar o projeto
pip install -e .

# 6. Verificar
python scripts\diagnose.py
```

### macOS

```bash
brew install python@3.12
# depois, os mesmos passos do Linux
```

---

## Verificação de funcionamento

```bash
# Diagnóstico completo (offline, ~1s)
python scripts/diagnose.py

# Inclui subir o Chromium de verdade
python scripts/diagnose.py --deep

# Suíte de testes
python -m pytest tests/ -q
# esperado: 21 passed

# CLI responde?
pinterest-board-dl --help
# ou, sem instalar:
python src/pinterest_board_dl.py --help

# Sintaxe
python -m py_compile src/pinterest_board_dl.py src/pinterest_board_gui.py
```

**Resultado esperado do diagnóstico:** `13 checagens | 0 falha(s) | 0 aviso(s)`.

---

## Primeiro uso

### GUI

```bash
pinterest-board-gui
# ou
python src/pinterest_board_gui.py
```

### CLI

```bash
# um quadro
pinterest-board-dl https://www.pinterest.com/usuario/quadro/

# todos os quadros de um usuário
pinterest-board-dl --user usuario_pinterest

# com tudo ligado
pinterest-board-dl <URL> --workers 32 --adaptive-workers --rate-limiting --json-log
```

### Extensão

1. Baixe o `.zip` (Chrome) ou `.xpi` (Firefox) da página de releases
2. Chrome: `chrome://extensions` → **Modo do desenvolvedor** → **Carregar sem compactação**
3. Firefox: `about:debugging` → **Extensão temporária** → carregar o `.xpi`

---

## Estrutura de diretórios

```
~/.cache/pinterest-downloader/          # Linux/macOS: cache de metadados
  └── .pinterest_cache.json
~/.config/pinterest-downloader/         # Linux/macOS: configuração
%LOCALAPPDATA%\pinterest-downloader\    # Windows: cache e config

./pins/                                 # downloads (default)
  └── <usuario>/
      └── <quadro>/
          └── *.jpg
```

Para usar outro local de cache: `--cache-dir /caminho`.

---

## Atualização

```bash
git pull origin main
pip install -r requirements.txt --upgrade
python scripts/diagnose.py
python -m pytest tests/ -q
```

---

## Desinstalação

### Linux/macOS
```bash
rm -rf ~/.cache/pinterest-downloader
rm -rf ~/.config/pinterest-downloader
# e o repositório:
cd .. && rm -rf pinterest_downloader
```

### Windows
```powershell
Remove-Item -Recurse "$env:LOCALAPPDATA\pinterest-downloader"
cd .. && Remove-Item -Recurse pinterest_downloader
```

---

## Problemas?

Veja [`RUNBOOK_TROUBLESHOOTING.md`](RUNBOOK_TROUBLESHOOTING.md).
