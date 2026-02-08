# 📖 Runbook: Instalação e Configuração

**App:** Pinterest Board Downloader v2.0.0  
**Suporte:** Linux (Ubuntu/Debian/Fedora) e Windows 10/11

---

## Requisitos do Sistema

### Hardware Mínimo
- **CPU:** Dual-core 2.0 GHz
- **RAM:** 4 GB
- **Disco:** 500 MB + espaço para downloads
- **Rede:** Conexão estável com internet

### Software
- Python 3.10 ou superior
- Navegador Chromium (instalado via Playwright)

---

## Instalação

### Linux (Ubuntu/Debian)

```bash
# 1. Clonar repositório
git clone https://github.com/yurix/my-pinterest-downloader.git
cd my-pinterest-downloader

# 2. Criar ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Instalar navegador Playwright
playwright install chromium

# 5. Testar instalação
python test_patches.py
```

### Linux (Fedora/RHEL)

```bash
# Dependências do sistema
sudo dnf install python3-pip python3-virtualenv

# Seguir passos 1-5 acima
```

### Windows

```powershell
# 1. Clonar repositório (Git Bash ou PowerShell)
git clone https://github.com/yurix/my-pinterest-downloader.git
cd my-pinterest-downloader

# 2. Criar ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Instalar navegador Playwright
playwright install chromium

# 5. Testar instalação
python test_patches.py
```

---

## Primeiro Uso

### Interface Gráfica (GUI)

```bash
# Linux
python pinterest_board_gui.py

# Windows
python pinterest_board_gui.py
```

### Linha de Comando (CLI)

```bash
# Download de um quadro único
python pinterest_board_dl.py https://www.pinterest.com/usuario/quadro/

# Download de todos os quadros de um usuário
python pinterest_board_dl.py --user username

# Com todas as otimizações
python pinterest_board_dl.py <URL> \
  --workers 32 \
  --adaptive-workers \
  --rate-limiting \
  --json-log
```

---

## Estrutura de Diretórios

Após instalação e uso:

```
~/.cache/pinterest-downloader/      # Linux: Cache de metadados
~/.config/pinterest-downloader/     # Linux: Configurações (futuro)

%LOCALAPPDATA%\pinterest-downloader\  # Windows: Cache e config

./pins/                              # Downloads (por padrão)
  └── <usuario>/
      └── <quadro>/
          └── *.jpg
```

---

## Verificação de Funcionamento

```bash
# Verificar sintaxe
python -m py_compile pinterest_board_dl.py

# Executar testes
python test_patches.py

# Diagnóstico completo
python diagnostics.py

# Verificar versão
python pinterest_board_dl.py --version
```

**Resultado esperado:** 11/11 testes PASS

---

## Atualização

```bash
# Puxar atualizações
git pull origin main

# Atualizar dependências
pip install -r requirements.txt --upgrade

# Verificar testes
python test_patches.py
```

---

## Desinstalação

### Linux
```bash
# Remover cache
rm -rf ~/.cache/pinterest-downloader

# Remover repositório
cd ..
rm -rf my-pinterest-downloader
```

### Windows
```powershell
# Remover cache
Remove-Item -Recurse "$env:LOCALAPPDATA\pinterest-downloader"

# Remover repositório
cd ..
Remove-Item -Recurse my-pinterest-downloader
```
