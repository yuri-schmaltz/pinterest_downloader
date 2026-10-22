# 🔧 Runbook: Troubleshooting

**App:** Pinterest Board Downloader v2.0.0

> Reescrito em 2026-10-22. A versão anterior mandava rodar
> `python diagnostics.py`, que foi removido no commit `9fb4c3e`. O substituto
> é [`scripts/diagnose.py`](../scripts/diagnose.py).

---

## Diagnóstico rápido

Antes de investigar qualquer coisa:

```bash
python scripts/diagnose.py
```

Verifica, em ~1 segundo, sem abrir navegador e sem tocar a rede:

- versão do Python e arquitetura
- `requests`, `playwright`, `psutil` instalados
- se os 5 módulos da aplicação importam
- se o Chromium do Playwright está presente
- se o cache e o config são graváveis
- se a extensão ainda referencia só arquivos existentes
- espaço em disco

Sai com código 1 se algo falhar. Use `--deep` para também subir o Chromium de
verdade, e `--json` para saída machine-readable (útil para CI e bug reports).

---

## Problemas comuns

### 1. `ModuleNotFoundError: No module named 'playwright'` (ou requests, psutil, PyQt6)

**Causa:** venv não ativado, ou dependência faltando.

```bash
source .venv/bin/activate          # Linux/macOS
.\.venv\Scripts\Activate.ps1       # Windows

pip install -r requirements.txt
python -m playwright install chromium
```

---

### 2. `ModuleNotFoundError: No module named 'pinterest_board_dl'`

**Causa:** código em `src/` com flat imports, e `src/` não está no path.

```bash
# se instalou o projeto:
pip install -e .

# se não instalou:
export PYTHONPATH=src
python -m pytest tests/ -q
```

Ao criar um **teste novo**, lembre de repetir o `sys.path.insert`:

```python
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
```

Foi exatamente essa migração para `src/` que zerou a suíte inteira de
testes em 2026-08-17 (o CI ficou vermelho até 2026-10-22).

---

### 3. "Nenhum pin encontrado (privado? login necessário?)"

**Causa:** quadro privado, ou o Pinterest exigindo login.

```bash
pinterest-board-dl <URL> --manual-login --headful
```

Faça login na janela do navegador que abrir. O processo retoma sozinho.

---

### 4. `TimeoutError` durante a coleta

**Causa:** rede lenta, ou Pinterest sobrecarregado.

```bash
# aumentar a pausa entre rolagens
pinterest-board-dl <URL> --scroll-pause 2.0

# reduzir o paralelismo
pinterest-board-dl <URL> --workers 4

# ativar a proteção contra 429
pinterest-board-dl <URL> --rate-limiting
```

---

### 5. Muitos erros HTTP 429 (Too Many Requests)

**Causa:** rate limit do Pinterest atingido.

```bash
pinterest-board-dl <URL> --rate-limiting
```

Para ver as estatísticas (o arquivo é gravado no diretório de onde você
chamou o comando):

```bash
cat rate_limit_stats.json
```

Se `total_429s` passar de 1 % do total de requests, reduza `--workers` para 8
ou menos.

---

### 6. A GUI não abre (Linux)

**Causa:** falta display, ou falta lib de sistema do Qt.

```bash
# tem display?
echo $DISPLAY          # esperado: :0 ou :1

# as libs de sistema estão lá?
python -c "from PyQt6.QtWidgets import QApplication; print('OK')"
# ImportError: libEGL.so.1 -> falta a lib:
sudo apt-get install -y libegl1 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3
```

Em máquina sem display (servidor, SSH sem X forwarding), a GUI não abre — use
a CLI. Para apenas testar que ela carrega:

```bash
QT_QPA_PLATFORM=offscreen python src/pinterest_board_gui.py
```

---

### 7. `ImportError: libEGL.so.1` ao rodar o AppImage

O AppImage já traz o Chromium, mas as libs de sistema do Qt precisam existir
no host. Em Ubuntu/Debian:

```bash
sudo apt-get install -y libegl1 libxkbcommon0 libxkbcommon-x11-0 \
    libdbus-1-3 libxcb-icccm4 libxcb-cursor0 libxcb-render-util0
```

---

### 8. Imagens não baixam / download incompleto

```bash
# ativar log estruturado
pinterest-board-dl <URL> --json-log --log-file download_log.json

# ver só os erros
jq '.logs[] | select(.level == "ERROR")' download_log.json
```

Re-executar aproveita o cache e pula o que já foi resolvido. Para forçar
re-download: `--no-cache`.

---

### 9. Cache corrompido

```bash
# Linux/macOS
rm -f ~/.cache/pinterest-downloader/.pinterest_cache.json

# Windows
del %LOCALAPPDATA%\pinterest-downloader\.pinterest_cache.json
```

O código trata cache corrompido gracefully (retorna cache vazio em vez de
quebrar), mas o arquivo é reescrito no próximo download.

---

### 10. Adaptive workers não ajustam

**Causa:** `psutil` não instalado.

```bash
pip install psutil
pinterest-board-dl <URL> --adaptive-workers
```

Métricas em `.worker_metrics.json`, no diretório atual:

```bash
jq '.metrics[-1]' .worker_metrics.json
```

---

### 11. A extensão não faz nada ao clicar no botão

Verifique, nesta ordem:

1. O `lib/i18n.js` está na pasta da extensão? (ele é carregado **antes** do
   `content.js` — sem ele o botão nem aparece):
   ```bash
   unzip -l pinterest-pro-downloader-chrome-*.zip | grep lib/i18n.js
   ```
2. Recarregue a extensão em `chrome://extensions` (o content script só é
   injetado em abas já abertas depois do carregamento).
3. Recarregue a página do Pinterest.

---

### 12. `pip install .` instala um pacote vazio

Isso acontecia antes da correção do `[tool.setuptools]`. Verifique:

```bash
pip install -e .
python -c "import pinterest_board_dl; print(pinterest_board_dl.__file__)"
```

Se imprimir um caminho em `site-packages`, está correto.

---

## Coletando diagnóstico para suporte

```bash
# 1. Diagnóstico em JSON
python scripts/diagnose.py --json > diagnostics.json

# 2. Versões
python --version
pip list | grep -E "playwright|PyQt6|requests|psutil"

# 3. Log do último download
ls -la ~/.cache/pinterest-downloader/ ./*.json 2>/dev/null

# 4. Erro específico
pinterest-board-dl <URL> --json-log 2>&1 | tee error_log.txt
```

Envie `diagnostics.json` e `error_log.txt`.

---

## Contato

- **Issues:** https://github.com/yuri-schmaltz/pinterest_downloader/issues
