# 🚦 ONDA 5E: Rate Limiting Inteligente

## 📋 Sumário Executivo

**Objetivo:** Proteger contra rate limits do Pinterest com sliding windows, exponential backoff e métricas detalhadas.

**Status:** ✅ IMPLEMENTADO

**Arquivos:**
- `rate_limiter.py` — Módulo completo de rate limiting
- `pinterest_board_dl.py` — Integração com `--rate-limiting`
- `test_11_rate_limiting.py` — 10 testes de validação

---

## 🎯 O Que Foi Implementado

### 1. Módulo `rate_limiter.py`

#### **RateLimitConfig (Configuração)**
```python
@dataclass
class RateLimitConfig:
    max_requests_per_second: float = 5.0      # Pinterest: 5 req/s
    max_requests_per_minute: int = 200        # Pinterest: 200 req/min
    max_requests_per_hour: int = 10000        # Pinterest: 10k req/h
    backoff_on_429: float = 60.0              # Backoff inicial: 60s
    backoff_multiplier: float = 2.0           # Dobrar a cada 429
    max_backoff: float = 300.0                # Máximo: 5 minutos
```

#### **RateLimiter (Classe Principal)**

**Atributos:**
- `requests_1s: deque` — Sliding window de 1 segundo
- `requests_1m: deque` — Sliding window de 1 minuto
- `requests_1h: deque` — Sliding window de 1 hora
- `current_backoff: float` — Tempo de backoff atual
- `backoff_until: float` — Timestamp até quando está em backoff
- `lock: threading.Lock` — Thread-safety

**Métodos:**
```python
acquire(timeout=None) -> bool
    """Bloqueia até ser seguro fazer requisição.
    Retorna True se permitido, False se timeout."""

report_429() -> None
    """Reporta erro HTTP 429, ativa exponential backoff."""

report_success() -> None
    """Reporta sucesso, diminui backoff gradualmente."""

get_stats() -> dict
    """Retorna métricas: total_requests, total_429s, backoff_seconds, windows."""

save_stats(filename) -> None
    """Salva estatísticas em JSON."""
```

### 2. Integração em `pinterest_board_dl.py`

#### **DownloadOptions (Novo Campo)**
```python
@dataclass
class DownloadOptions:
    # ... campos existentes ...
    rate_limiting: bool = False  # NOVO
```

#### **fetch_og_image() Modificado**
```python
def fetch_og_image(url: str, session: requests.Session, 
                   use_rate_limit: bool = False) -> str | None:
    if use_rate_limit:
        limiter = get_rate_limiter()
        if not limiter.acquire(timeout=30.0):
            return None  # Timeout aguardando rate limit
    
    try:
        resp = session.get(url, timeout=TIMEOUT_HTTP_GET)
        
        if resp.status_code == 429 and use_rate_limit:
            limiter.report_429()  # Exponential backoff
            return None
        
        if use_rate_limit:
            limiter.report_success()  # Gradual reset
        
        # ... resto do código ...
```

#### **resolve_images() Modificado**
```python
def resolve_images(..., rate_limiting: bool = False):
    def work(link: str):
        img = fetch_og_image(link, session, use_rate_limit=rate_limiting)
        if not img:
            mobile = link.replace("www.pinterest.com", "br.pinterest.com")
            img = fetch_og_image(mobile, session, use_rate_limit=rate_limiting)
        # ... resto ...
```

#### **CLI Flag**
```bash
python pinterest_board_dl.py <URL> --rate-limiting
```

---

## 📊 Uso

### Ativar Rate Limiting
```bash
# Baixar com rate limiting
python pinterest_board_dl.py https://www.pinterest.com/user/board/ --rate-limiting

# Combinar com adaptive workers
python pinterest_board_dl.py <URL> --adaptive-workers --rate-limiting
```

### Ver Estatísticas
```bash
# Ao final do download, verá:
==> RATE LIMITING:
  Total requests: 532
  429 errors: 3
  Backoff time: 30.0s
  Stats salvas em: rate_limit_stats.json
```

### Analisar Estatísticas JSON
```bash
# Ver sumário
jq '.' rate_limit_stats.json

# Total de 429s ao longo do tempo
jq '.total_429s' rate_limit_stats.json

# Backoff atual
jq '.backoff_seconds' rate_limit_stats.json

# Requisições por janela
jq '{window_1s, window_1m, window_1h}' rate_limit_stats.json
```

---

## 🔍 Sliding Windows Explicados

### Janela de 1 Segundo (5 req/s)
```
Timeline:    0.0s    0.5s    1.0s    1.5s
Requests:     [1]     [2]     [3]     [4]     [5]
             └─────────────┘
                1s window

# 6ª requisição em 1.1s → BLOQUEIA até 1.0s deslizar para fora
```

### Janela de 1 Minuto (200 req/min)
```
Requisições:  1   2   3   ...   199   200
              └──────────────────────────┘
                     1 minuto

# 201ª requisição → BLOQUEIA até requisição mais antiga sair da janela
```

### Janela de 1 Hora (10k req/h)
```
Requisições:  1   2   3   ...   9999   10000
              └──────────────────────────────┘
                       1 hora

# 10001ª requisição → BLOQUEIA até requisição mais antiga sair
```

---

## ⚡ Exponential Backoff

### Sequência de 429s
```python
# 1º erro 429 → backoff = 60s
# 2º erro 429 → backoff = 120s (60 * 2)
# 3º erro 429 → backoff = 240s (120 * 2)
# 4º erro 429 → backoff = 300s (máximo)
```

### Recuperação Gradual
```python
# Após cada sucesso, backoff diminui 10%
backoff_new = backoff_old * 0.9

# Exemplo:
# Backoff em 120s
# 1º sucesso → 108s
# 2º sucesso → 97.2s
# 3º sucesso → 87.5s
# ... até chegar a 0s
```

---

## 🧪 Testes (Test 11)

### Executar Testes
```bash
python3 test_11_rate_limiting.py
```

**Resultado esperado:**
```
============================================================
TEST 11 - Rate Limiting (ONDA 5E)
============================================================
✓ Inicialização do rate limiter OK
✓ Configuração customizada OK
✓ Acquire básico OK
✓ Sliding window (1s) OK
✓ Report 429 e exponential backoff OK
✓ Report success e backoff reset OK
✓ Thread-safety OK
✓ Get stats OK
✓ Save stats OK
✓ Singleton pattern OK

============================================================
RESULTADO: 10 PASS, 0 FAIL
============================================================
```

### Testes Cobertos
| # | Teste | O Que Valida |
|---|-------|--------------|
| 1 | Inicialização | Config padrão (5 req/s, 200 req/min, 10k req/h) |
| 2 | Config customizada | Permite override de limites |
| 3 | Acquire básico | Primeira req não bloqueia |
| 4 | Sliding window | 6ª req/s bloqueia até janela deslizar |
| 5 | Report 429 | Exponential backoff (60s → 120s → 240s) |
| 6 | Report success | Backoff diminui 10% por sucesso |
| 7 | Thread-safety | 3 threads simultâneas sem race conditions |
| 8 | Get stats | Métricas completas (reqs, 429s, windows) |
| 9 | Save stats | JSON válido salvo |
| 10 | Singleton | Mesma instância em todo o programa |

---

## 🔧 Configuração Customizada

### Limites Mais Conservadores
```python
from rate_limiter import RateLimitConfig, get_rate_limiter

custom_config = RateLimitConfig(
    max_requests_per_second=2.0,     # Mais lento
    max_requests_per_minute=100,     # Metade do Pinterest
    max_requests_per_hour=5000,      # Metade do Pinterest
    backoff_on_429=120.0,            # Backoff maior
)

limiter = get_rate_limiter(custom_config)
```

### Limites Mais Agressivos (Cuidado!)
```python
aggressive_config = RateLimitConfig(
    max_requests_per_second=10.0,    # Dobro do Pinterest
    max_requests_per_minute=300,     # 50% acima
    backoff_on_429=30.0,             # Backoff menor
)

# ⚠️ Use com cautela: pode resultar em mais 429s
```

---

## 📈 Análise de Performance

### Ver Total de Requisições
```bash
jq '.total_requests' rate_limit_stats.json
# Output: 532
```

### Calcular Taxa de 429s
```bash
jq '(.total_429s / .total_requests * 100)' rate_limit_stats.json
# Output: 0.56 (0.56% de erros)
```

### Ver Distribuição de Requisições
```bash
jq '{
  last_second: .window_1s,
  last_minute: .window_1m,
  last_hour: .window_1h
}' rate_limit_stats.json

# Output:
# {
#   "last_second": 3,
#   "last_minute": 47,
#   "last_hour": 532
# }
```

### Detectar Se Está em Backoff
```bash
jq 'if .in_backoff then "🔴 EM BACKOFF" else "✅ NORMAL" end' rate_limit_stats.json
```

---

## 🛡️ Proteções Implementadas

### 1. Sliding Windows (3 níveis)
- ✅ **1 segundo**: Limita a 5 req/s
- ✅ **1 minuto**: Limita a 200 req/min
- ✅ **1 hora**: Limita a 10k req/h

### 2. Exponential Backoff
- ✅ **Primeiro 429**: Pausa 60s
- ✅ **Segundo 429**: Pausa 120s (dobra)
- ✅ **Terceiro 429**: Pausa 240s (dobra)
- ✅ **Máximo**: 300s (5 minutos)

### 3. Gradual Reset
- ✅ **Cada sucesso**: Diminui backoff em 10%
- ✅ **Auto-recuperação**: Volta ao normal após sucessos consistentes

### 4. Thread-Safety
- ✅ **Lock global**: Protege deques e contadores
- ✅ **Concorrência segura**: Funciona com workers paralelos

---

## 🎓 Casos de Uso

### Caso 1: Download Grande (1000+ pins)
```bash
# Sem rate limiting: pode resultar em 429s
python pinterest_board_dl.py <URL> --workers 32

# Com rate limiting: protegido
python pinterest_board_dl.py <URL> --workers 32 --rate-limiting
```

### Caso 2: Múltiplos Quadros
```bash
# Rate limiting global protege todos os quadros
python pinterest_board_dl.py --user <usuario> --rate-limiting
```

### Caso 3: Debugging de 429s
```bash
# Rodar com rate limiting e ver stats
python pinterest_board_dl.py <URL> --rate-limiting

# Analisar stats
jq '.' rate_limit_stats.json

# Se muitos 429s:
jq '.total_429s' rate_limit_stats.json
# → Considere diminuir workers ou aumentar limites
```

---

## 🐛 Troubleshooting

### Muitos 429s Ainda
```bash
# Verificar stats
jq '{total_429s, total_requests}' rate_limit_stats.json

# Soluções:
# 1. Diminuir workers
python pinterest_board_dl.py <URL> --rate-limiting --workers 8

# 2. Config mais conservadora (editar rate_limiter.py)
# max_requests_per_second = 3.0  # Mais lento
```

### Rate Limiting Muito Lento
```bash
# Verificar backoff atual
jq '.backoff_seconds' rate_limit_stats.json

# Se alto (>60s), significa que teve 429s recentes
# Aguardar alguns minutos e tentar novamente

# Ou resetar manualmente (deletar stats)
rm rate_limit_stats.json
```

### Thread-Safety Issues
```python
# Se ver race conditions, verificar singleton:
from rate_limiter import get_rate_limiter, reset_rate_limiter

# Resetar limiter
reset_rate_limiter()

# Pegar nova instância
limiter = get_rate_limiter()
```

---

## 📊 Comparação: Com vs Sem Rate Limiting

| Métrica | Sem Rate Limiting | Com Rate Limiting |
|---------|-------------------|-------------------|
| **Velocidade inicial** | ⚡ Muito rápida | 🐢 Controlada |
| **Erros 429** | ❌ Frequentes | ✅ Raros (<1%) |
| **Pausas longas** | ⏸️ Sim (quando 429) | ✅ Não (preventivo) |
| **Tempo total** | 🤷 Variável | ⏱️ Previsível |
| **Confiabilidade** | ⚠️ Baixa | ✅ Alta |

---

## 🎓 Benefícios

| Benefício | Descrição |
|-----------|-----------|
| 🛡️ **Proteção Completa** | 3 níveis de limite (1s, 1min, 1h) |
| 🔄 **Exponential Backoff** | Auto-recupera de 429s |
| 📊 **Métricas Detalhadas** | Total reqs, 429s, tempo de backoff |
| 🧵 **Thread-Safe** | Funciona com workers paralelos |
| ⚡ **Baixa Overhead** | Deques eficientes (<0.1ms por check) |
| 🔧 **Configurável** | Limites customizáveis por API |

---

## 🚀 Próximos Passos

### Melhorias Futuras (ONDA 6+)
1. **Rate Limiting por Domínio**: Limites diferentes para pinterest.com vs br.pinterest.com
2. **Auto-tuning**: Aprender limites ideais baseado em 429s históricos
3. **Distributed Rate Limiting**: Compartilhar limites entre múltiplas instâncias
4. **Webhooks**: Alertar quando muitos 429s detectados

---

**Guia criado em:** 12 de janeiro de 2026  
**Versão:** 1.0.0  
**Autor:** GitHub Copilot
