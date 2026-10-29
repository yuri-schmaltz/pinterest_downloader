> **Documento histórico — 12 de janeiro de 2026.**
> Descreve o estado do projeto na época da ONDA 5B. O código evoluiu
> bastante desde então: o repositório foi reestruturado para `src/`, a suíte
> de testes foi reescrita e o CI foi corrigido.
>
> - Estado atual: [`PROJECT.md`](../PROJECT.md) · [`PLANO-ESTABILIZACAO.md`](../PLANO-ESTABILIZACAO.md) · [`TEST_INFRA.md`](../TEST_INFRA.md)
> - Comandos quebrados citados abaixo foram atualizados para os equivalents
>   que existem hoje.
>
> ---

# 📊 ONDA 5B: Guia de Uso - Logging Estruturado em JSON

## 🎯 O que é?

Sistema de logging estruturado que registra cada fase de download com **timestamps ISO 8601** e **métricas de performance**, permitindo auditoria e análise posterior.

---

## 🚀 Uso Rápido

### Ativar Logging JSON

```bash
# Formato básico
python src/pinterest_board_dl.py --user yuri_schmaltz --json-log

# Com arquivo customizado
python src/pinterest_board_dl.py --board https://www.pinterest.com/user/board/ --json-log --log-file my_log.json

# Quadro específico com logging
python src/pinterest_board_dl.py https://www.pinterest.com/user/board/ --json-log
```

### Visualizar Logs

```bash
# Formatado (legível)
cat download_log.json | python -m json.tool

# Contar entradas
jq '.total_entries' download_log.json

# Listar todas as fases
jq '.logs[] | {timestamp, phase, level, message}' download_log.json
```

---

## 📋 Estrutura do JSON

### Arquivo Completo
```json
{
  "version": "1.0",
  "generated_at": "2026-01-11T15:30:45.123Z",
  "total_entries": 15,
  "logs": [
    {
      "timestamp": "2026-01-11T15:30:45.100Z",
      "phase": "download_user_boards",
      "level": "INFO",
      "message": "Iniciando downloads do usuário: yuri_schmaltz",
      "board_url": "yuri_schmaltz",
      "metadata": {}
    },
    {
      "timestamp": "2026-01-11T15:30:47.250Z",
      "phase": "download_user_boards",
      "level": "INFO",
      "message": "Encontrados 5 quadros",
      "board_url": "yuri_schmaltz",
      "count": 5,
      "metadata": {}
    },
    {
      "timestamp": "2026-01-11T15:30:50.100Z",
      "phase": "download_board",
      "level": "INFO",
      "message": "Iniciando download: https://www.pinterest.com/yuri_schmaltz/design/",
      "board_url": "https://www.pinterest.com/yuri_schmaltz/design/",
      "metadata": {}
    },
    {
      "timestamp": "2026-01-11T15:31:05.500Z",
      "phase": "resolve_images",
      "level": "INFO",
      "message": "Resolvidas 245 imagens (cache: 120)",
      "count": 245,
      "duration_ms": 8245.75,
      "metadata": {}
    },
    {
      "timestamp": "2026-01-11T15:31:25.800Z",
      "phase": "download_board",
      "level": "INFO",
      "message": "Baixadas 245/245 imagens",
      "count": 245,
      "duration_ms": 35700.0,
      "metadata": {}
    }
  ]
}
```

---

## 🔍 Exemplos de Análise

### 1. Tempo total por fase

```bash
jq '.logs[] | select(.duration_ms != null) | {phase, duration_ms}' download_log.json
```

**Output:**
```json
{
  "phase": "resolve_images",
  "duration_ms": 8245.75
}
{
  "phase": "download_board",
  "duration_ms": 35700.0
}
```

### 2. Contar imagens resolvidas vs baixadas

```bash
jq '.logs[] | select(.level == "INFO") | {phase, message, count}' download_log.json
```

### 3. Verificar se houve erros/avisos

```bash
jq '.logs[] | select(.level != "INFO")' download_log.json
```

### 4. Agrupar por quadro

```bash
jq 'group_by(.board_url) | map({board: .[0].board_url, count: length})' download_log.json
```

---

## 📊 Campos do Log

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `timestamp` | string (ISO 8601) | Quando o evento aconteceu (UTC) |
| `phase` | string | Fase do processo: `download_board`, `resolve_images`, `download_user_boards`, etc |
| `level` | string | `INFO`, `WARN`, `ERROR` |
| `message` | string | Descrição legível do evento |
| `duration_ms` | float (opcional) | Duração em milissegundos (só em phase end) |
| `board_url` | string (opcional) | URL ou usuário sendo processado |
| `count` | int (opcional) | Contador: pins, imagens, downloads |
| `error` | string (opcional) | Mensagem de erro (se level=ERROR) |
| `metadata` | object (opcional) | Dados adicionais customizados |

---

## 🎯 Casos de Uso

### Auditoria
```bash
# Verificar quais quadros foram processados e quando
jq '.logs[] | select(.message | contains("Iniciando")) | {timestamp, board_url}' download_log.json
```

### Performance
```bash
# Identificar fase mais lenta
jq '.logs[] | select(.duration_ms != null) | sort_by(-.duration_ms) | .[0]' download_log.json
```

### Debugging
```bash
# Todos os eventos de um quadro específico
jq '.logs[] | select(.board_url | contains("design"))' download_log.json

# Todos os warnings/errors
jq '.logs[] | select(.level | test("WARN|ERROR"))' download_log.json
```

### Estatísticas
```bash
# Total de imagens baixadas em uma sessão
jq '.logs[] | select(.phase == "download_board") | .count | add' download_log.json
```

---

## ⚙️ Configuração Avançada

### Desabilitar logging (padrão)
```bash
python src/pinterest_board_dl.py --user yuri_schmaltz
# Nenhum arquivo JSON será criado
```

### Habilitar com arquivo customizado
```bash
python src/pinterest_board_dl.py --user yuri_schmaltz --json-log --log-file /tmp/pins_$(date +%s).json
```

### Combinar com outras flags
```bash
python src/pinterest_board_dl.py \
  --user yuri_schmaltz \
  --out ./downloads \
  --workers 24 \
  --max-pins 500 \
  --json-log \
  --log-file ./audit/$(date +%Y%m%d).json
```

---

## 📝 Notas Técnicas

### Timestamps
- Formato: ISO 8601 UTC (ex: `2026-01-11T15:30:45.123Z`)
- Precisão: milissegundos
- Zona: Z (Zulu = UTC)

### Duração
- Medida em milissegundos
- Precisão: até 6 decimais
- Calculada automaticamente entre `start_phase()` e `end_phase()`

### Singleton Global
```python
# Dentro do código Python
from json_logger import get_logger, reset_logger

logger = get_logger()  # Obtém instância global
logger.start_phase("my_phase")
# ... faça algo ...
logger.end_phase("my_phase", count=42)
logger.save()  # Salva em JSON

# Em testes, resetar:
reset_logger()
```

---

## 🧪 Teste

```bash
# Executar teste de funcionalidade (TEST 9)
python -m pytest tests/ -q

# Deve passar com:
# ✅ PASS: JSON Logger funciona corretamente (ONDA 5B)
```

---

## 🔗 Referências

- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) — Documentação técnica
- [json_logger.py](json_logger.py) — Código-fonte do módulo
- [pinterest_board_dl.py](pinterest_board_dl.py) — Integração com CLI

---

**Última atualização:** 11 de janeiro de 2026  
**Status:** ✅ ONDA 5B Completa
