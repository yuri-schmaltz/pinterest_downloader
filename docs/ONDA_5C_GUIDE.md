# 🚀 ONDA 5C: Guia de Uso - Adaptive Workers

## 🎯 O que é?

Sistema inteligente que **ajusta automaticamente** o número de threads de trabalho baseado em:
- **CPU disponível** (alvo: 70%)
- **RAM disponível** (alvo: 60%)
- **Taxa de sucesso** (mínimo 80%)
- **Latência de rede** (milissegundos)

Resultado: máxima performance sem sobrecarregar o sistema.

---

## 🚀 Uso Rápido

### Ativar Adaptive Workers

```bash
# Formato básico (recomendado: --workers = max desejado)
python pinterest_board_dl.py --user yuri_schmaltz --workers 32 --adaptive-workers

# Com quadro específico
python pinterest_board_dl.py https://www.pinterest.com/user/board/ --workers 24 --adaptive-workers

# Combinar com logging JSON
python pinterest_board_dl.py --user yuri_schmaltz --workers 32 --adaptive-workers --json-log
```

### Visualizar Métricas Coletadas

```bash
# Formatado (legível)
cat .worker_metrics.json | python -m json.tool

# Contar amostras
jq '.total_samples' .worker_metrics.json

# Histórico de workers ajustados
jq '.metrics[] | {timestamp, active_workers, cpu_percent, memory_percent}' .worker_metrics.json

# Gráfico simples: workers ao longo do tempo
jq '.metrics[] | "\(.timestamp) workers=\(.active_workers) cpu=\(.cpu_percent|floor)% mem=\(.memory_percent|floor)%"' .worker_metrics.json
```

---

## 📊 Como Funciona

### Fluxo de Ajuste

```
┌─────────────────────────────────────────────────────┐
│  A cada 10 requisições resolvidas:                 │
└─────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Medir sistema agora   │
        │ • CPU %               │
        │ • RAM %               │
        │ • Success rate        │
        │ • Avg latency         │
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Registrar métrica     │
        │ em .worker_metrics    │
        └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Decidir ajuste:       │
        │ Aumentar? Diminuir?   │
        └───────────────────────┘
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
    ┌─────────┐          ┌──────────┐
    │ +1 work │          │ -1 work  │ (se necessário)
    └─────────┘          └──────────┘
        │                     │
        └──────────┬──────────┘
                   ▼
        ┌───────────────────────┐
        │ Continuar com N novo  │
        │ workers na próxima    │
        │ rodada de requests    │
        └───────────────────────┘
```

### Critérios de Ajuste

**AUMENTAR workers se:**
```
CPU < 49% (70% × 0.7)  AND
Memory < 48% (60% × 0.8) AND
Success rate > 95%
→ workers += 1
```

**DIMINUIR workers se:**
```
CPU > 70% OR
Memory > 60% OR
Success rate < 80%
→ workers -= 1
```

---

## 📋 Campos da Métrica

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `timestamp` | string (ISO 8601) | Quando foi amostrado (UTC) |
| `cpu_percent` | float | % de CPU em uso no sistema |
| `memory_percent` | float | % de RAM em uso no sistema |
| `active_workers` | int | Número de workers no momento |
| `success_rate` | float | Taxa de sucesso (0-1) |
| `avg_latency_ms` | float | Latência média de requisição (ms) |

---

## 🔍 Exemplos de Análise

### 1. Verificar se workers foram ajustados

```bash
jq '.metrics | map(.active_workers) | unique' .worker_metrics.json
# Output: [8, 10, 12, 14]  ← Workers variaram entre 8 e 14
```

### 2. Mostrar tendência: Workers vs CPU

```bash
jq '.metrics[] | "\(.active_workers) workers: CPU=\(.cpu_percent|floor)%"' .worker_metrics.json | sort | uniq -c
```

**Output típico:**
```
  5 8 workers: CPU=35%
 12 10 workers: CPU=55%
 20 12 workers: CPU=68%
  3 14 workers: CPU=75%
  1 12 workers: CPU=70%  ← voltou pra baixo
```

### 3. Encontrar ponto ótimo

```bash
jq '.metrics | max_by(.success_rate)' .worker_metrics.json
# Mostra a amostra com maior success_rate
```

### 4. Performance final

```bash
jq '{
  final_workers: .current_workers,
  success_rate: (.success_rate * 100 | round),
  avg_latency_ms: (.avg_latency_ms | round),
  total_requests: (.total_samples * 10)  # aprox, já que ajusta a cada 10
}' .worker_metrics.json
```

---

## 📊 Estrutura Completa do JSON

```json
{
  "version": "1.0",
  "generated_at": "2026-01-12T14:32:50.123Z",
  "total_samples": 47,
  "current_workers": 12,
  "success_rate": 0.978,
  "avg_latency_ms": 248.5,
  "metrics": [
    {
      "timestamp": "2026-01-12T14:30:10.200Z",
      "cpu_percent": 32.4,
      "memory_percent": 45.2,
      "active_workers": 8,
      "success_rate": 1.0,
      "avg_latency_ms": 310.0
    },
    {
      "timestamp": "2026-01-12T14:30:20.400Z",
      "cpu_percent": 52.1,
      "memory_percent": 51.8,
      "active_workers": 10,
      "success_rate": 0.99,
      "avg_latency_ms": 285.5
    },
    {
      "timestamp": "2026-01-12T14:30:30.600Z",
      "cpu_percent": 68.3,
      "memory_percent": 58.9,
      "active_workers": 12,
      "success_rate": 0.98,
      "avg_latency_ms": 260.2
    },
    {
      "timestamp": "2026-01-12T14:30:40.800Z",
      "cpu_percent": 72.1,
      "memory_percent": 62.4,
      "active_workers": 11,
      "success_rate": 0.97,
      "avg_latency_ms": 275.8
    }
  ]
}
```

---

## 🛠️ Configuração Avançada

### Limites Customizados

No código Python, editar `resolve_images()`:

```python
# Default: min=4, max=workers (CLI param)
manager = get_adaptive_manager(min_workers=2, max_workers=64)

# Ou editar em adaptive_workers.py:
AdaptiveWorkerManager(
    min_workers=4,        # Não desce de 4
    max_workers=32,       # Não sobe de 32
    target_cpu_percent=70.0,    # CPU alvo
    target_memory_percent=60.0, # RAM alva
)
```

### Desabilitar (fallback para static workers)

```bash
# Sem --adaptive-workers: usa fixed --workers value
python pinterest_board_dl.py --user yuri_schmaltz --workers 16
# Neste caso, sempre 16 workers (sem ajuste)
```

---

## ⚡ Performance Esperada

### Cenário 1: Sistema com pouca carga
```
início: 4 workers
durante: aumenta gradualmente até 16 (CPU < 50%)
resultado: ~30% mais rápido que fixed workers
```

### Cenário 2: Sistema com muita carga
```
início: 16 workers (CLI: --workers 16)
durante: cai para 8-12 (CPU > 70%)
resultado: sem travamentos, completa mesmo assim
```

### Cenário 3: Rede instável
```
início: 12 workers
quando: sucesso_rate cai para <80%
ação: reduz para 10
efeito: melhor timeout/retry recovery
```

---

## 🧪 Teste

```bash
# Executar teste de funcionalidade (TEST 10)
python test_patches.py | grep -A 5 "TEST 10"

# Deve passar com:
# ✅ PASS: Adaptive Workers funciona corretamente (ONDA 5C)
```

---

## 📝 Dicas Práticas

### 1. Descobrir o --workers ideal para seu hardware

```bash
# Rodar UMA VEZ com --adaptive-workers
python pinterest_board_dl.py --user yuri_schmaltz --workers 32 --adaptive-workers

# Observar em .worker_metrics.json qual workers foi mais eficiente
jq '.metrics | group_by(.active_workers) | map({
  workers: .[0].active_workers, 
  count: length,
  avg_success: (map(.success_rate) | add/length | . * 100 | round)
})' .worker_metrics.json
```

### 2. Monitorar em tempo real

```bash
# Terminal 1: começar download
python pinterest_board_dl.py --user yuri_schmaltz --workers 32 --adaptive-workers

# Terminal 2: monitorar ajustes (a cada 1s)
watch -n 1 'jq ".metrics[-1] | {workers: .active_workers, cpu: .cpu_percent, mem: .memory_percent, success: .success_rate}" .worker_metrics.json'
```

### 3. Comparar adaptive vs fixed

```bash
# Run 1: Com adaptive
python pinterest_board_dl.py --user yuri_schmaltz --workers 32 --adaptive-workers --json-log --log-file log_adaptive.json

# Run 2: Sem adaptive (usar workers médio do run anterior)
python pinterest_board_dl.py --user yuri_schmaltz --workers 12 --json-log --log-file log_fixed.json

# Comparar duração das fases
echo "=== Adaptive ===" && jq '.logs[-1] | {phase, duration_ms}' log_adaptive.json
echo "=== Fixed ===" && jq '.logs[-1] | {phase, duration_ms}' log_fixed.json
```

---

## 🔗 Referências

- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md#-onda-5c-adaptive-workers-ajuste-dinâmico-de-paralelismo--) — Documentação técnica
- [adaptive_workers.py](adaptive_workers.py) — Código-fonte do módulo
- [pinterest_board_dl.py](pinterest_board_dl.py) — Integração com CLI
- [.worker_metrics.json](.worker_metrics.json) — Exemplo de saída

---

## 📈 Roadmap ONDA 5D+ (Futuro)

- **ONDA 5D:** CI Benchmarks (GitHub Actions com histórico)
- **ONDA 5E:** Rate limiting inteligente (respeitar limits do Pinterest)
- **ONDA 5F:** WebSocket para notificações em tempo real

---

**Última atualização:** 12 de janeiro de 2026  
**Status:** ✅ ONDA 5C Completa
