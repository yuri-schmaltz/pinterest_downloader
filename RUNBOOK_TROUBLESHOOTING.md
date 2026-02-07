# 🔧 Runbook: Troubleshooting

**App:** Pinterest Board Downloader v2.0.0

---

## Diagnóstico Rápido

Antes de investigar, execute:

```bash
python diagnostics.py
```

Este script verifica:
- ✅ Dependências instaladas
- ✅ Playwright funcionando
- ✅ Conectividade com Pinterest
- ✅ Permissões de escrita

---

## Problemas Comuns

### 1. "ModuleNotFoundError: No module named 'playwright'"

**Causa:** Ambiente virtual não ativado ou dependência não instalada.

**Solução:**
```bash
# Ativar ambiente virtual
source .venv/bin/activate  # Linux
.\.venv\Scripts\Activate.ps1  # Windows

# Reinstalar dependências
pip install -r requirements.txt
playwright install chromium
```

---

### 2. "Nenhum pin encontrado (privado? login necessário?)"

**Causa:** Quadro privado ou Pinterest requerendo login.

**Solução:**
```bash
# Usar modo login manual
python pinterest_board_dl.py <URL> --manual-login --headful

# Faça login na janela que abre
# Pressione ENTER no terminal para continuar
```

---

### 3. "TimeoutError" durante coleta de pins

**Causa:** Rede lenta ou Pinterest sobrecarregado.

**Soluções:**
```bash
# Aumentar tempo de scroll
python pinterest_board_dl.py <URL> --scroll-pause 2.0

# Reduzir workers
python pinterest_board_dl.py <URL> --workers 4

# Ativar rate limiting
python pinterest_board_dl.py <URL> --rate-limiting
```

---

### 4. Muitos erros HTTP 429 (Too Many Requests)

**Causa:** Rate limiting do Pinterest atingido.

**Solução:**
```bash
# Ativar proteção automática
python pinterest_board_dl.py <URL> --rate-limiting

# Verificar estatísticas
cat rate_limit_stats.json
```

**Métricas esperadas:**
- `total_429s < 1%` do total de requests
- Se maior, reduzir `--workers` para 8 ou menos

---

### 5. GUI não abre (Linux)

**Causa:** Display não configurado ou PyQt6 faltando.

**Verificar:**
```bash
# Verificar display
echo $DISPLAY  # Deve mostrar :0 ou :1

# Testar PyQt6
python -c "from PyQt6.QtWidgets import QApplication; print('OK')"
```

**Soluções:**
```bash
# Se $DISPLAY vazio (SSH sem X forwarding)
export DISPLAY=:0

# Se erro de PyQt6
pip install PyQt6 --upgrade
```

---

### 6. Imagens não baixam / download incompleto

**Causa:** Rede instável ou timeout de download.

**Verificar logs:**
```bash
# Ativar logging JSON
python pinterest_board_dl.py <URL> --json-log

# Analisar erros
jq '.logs[] | select(.level == "ERROR")' download_log.json
```

**Soluções:**
```bash
# Re-executar (usa cache, pula já resolvidos)
python pinterest_board_dl.py <URL>

# Aumentar timeout (modificar constante se necessário)
# TIMEOUT_IMAGE_DOWNLOAD = 120  # em pinterest_board_dl.py
```

---

### 7. Cache corrompido

**Sintoma:** Erros ao carregar cache JSON.

**Solução:**
```bash
# Linux
rm ~/.cache/pinterest-downloader/.pinterest_cache.json

# Windows
del %LOCALAPPDATA%\pinterest-downloader\.pinterest_cache.json

# Re-executar download
python pinterest_board_dl.py <URL>
```

---

### 8. Workers adaptativos não ajustam

**Causa:** psutil não instalado.

**Solução:**
```bash
pip install psutil
python pinterest_board_dl.py <URL> --adaptive-workers
```

**Verificar métricas:**
```bash
jq '.metrics[-1]' .worker_metrics.json
```

---

## Coleta de Diagnóstico para Suporte

Se o problema persistir, colete:

```bash
# 1. Versões
python --version
pip list | grep -E "(playwright|PyQt6|requests|psutil)"

# 2. Diagnóstico
python diagnostics.py > diagnostics_output.txt

# 3. Logs do último download
ls -la download_log.json rate_limit_stats.json .worker_metrics.json

# 4. Erro específico
python pinterest_board_dl.py <URL> --json-log 2>&1 | tee error_log.txt
```

Envie:
- `diagnostics_output.txt`
- `error_log.txt`
- `download_log.json` (se existir)

---

## Contato

- **Issues:** https://github.com/yurix/my-pinterest-downloader/issues
- **Discussions:** https://github.com/yurix/my-pinterest-downloader/discussions
