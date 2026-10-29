> **Documento histórico — 12 de janeiro de 2026.**
> Descreve o estado do projeto na época da ONDA 5D. O código evoluiu
> bastante desde então: o repositório foi reestruturado para `src/`, a suíte
> de testes foi reescrita e o CI foi corrigido.
>
> - Estado atual: [`PROJECT.md`](../PROJECT.md) · [`PLANO-ESTABILIZACAO.md`](../PLANO-ESTABILIZACAO.md) · [`TEST_INFRA.md`](../TEST_INFRA.md)
> - Comandos quebrados citados abaixo foram atualizados para os equivalents
>   que existem hoje.
> - ⚠️ Este guia descreve o workflow de CI **antigo** (job de benchmark com
>   `diagnostics.py` e `diagnostics_baseline.json`). O job de benchmark foi
>   removido — o arquivo de baseline nunca existiu no repositório e o job
>   falhava em todo push. O CI atual tem quatro jobs, sem benchmark.
>
> ---

# 🚀 ONDA 5D: CI Benchmarks com GitHub Actions

## 📋 Sumário Executivo

**Objetivo:** Automatizar testes, benchmarking e análise de performance no CI/CD usando GitHub Actions.

**Status:** ✅ IMPLEMENTADO

**Arquivos:**
- `.github/workflows/tests.yml` — Workflow completo (test + benchmark + lint)
- `benchmark.py` — Script de benchmarking local

---

## 🎯 O Que Foi Implementado

### 1. GitHub Actions Workflow

#### **Job 1: Test Matrix** (Python 3.10, 3.11, 3.12)
```yaml
test:
  strategy:
    matrix:
      python-version: ["3.10", "3.11", "3.12"]
  steps:
    - Checkout code
    - Setup Python ${{ matrix.python-version }}
    - Install dependencies
    - Run smoke tests (test_patches.py)
    - Syntax validation
```

#### **Job 2: Benchmark**
```yaml
benchmark:
  steps:
    - Checkout with history
    - Run benchmark.py
    - Compare with baseline
    - Upload artifacts
    - Comment on PRs with results
```

#### **Job 3: Lint**
```yaml
lint:
  steps:
    - Black formatting check
    - Ruff linting (E, W, F, I, C, B)
    - MyPy type checking
```

### 2. Local Benchmarking Script

**`benchmark.py` faz:**
1. Executa `diagnostics.py` e captura JSON
2. Executa `test_patches.py` e conta PASS/FAIL
3. Compara com baseline anterior (git diff)
4. Salva relatório JSON com timestamp e commit SHA
5. Exibe sumário visual

---

## 📊 Uso Local

### Rodar Benchmark Completo
```bash
python3 benchmark.py
```

**Saída:**
```
╔══════════════════════════════════════════════════════════╗
║                🎯 BENCHMARK RUNNER - ONDA 5D              ║
╚══════════════════════════════════════════════════════════╝

🧪 Smoke Tests:
   Passed: 11
   Duration: 3.0s

🔍 Diagnostics:
   Checks: 0/0

📦 Git Commit: bccc4247
⏰ Timestamp: 2026-01-12T04:21:19.296Z

💾 Relatório salvo em: benchmark_1768191683.json
```

### Analisar Relatório JSON
```bash
# Ver sumário
jq '{commit, timestamp, tests_passed, duration_seconds}' benchmark_*.json

# Ver comparação com baseline
jq '.comparison' benchmark_*.json

# Últimos 5 benchmarks
ls -lt benchmark_*.json | head -5
```

---

## 🔍 Estrutura do Relatório JSON

```json
{
  "timestamp": "2026-01-12T04:21:19.296Z",
  "commit": "bccc4247",
  "branch": "main",
  "smoke_tests": {
    "passed": 11,
    "failed": 0,
    "duration_seconds": 3.0
  },
  "diagnostics": {
    "total_checks": 0,
    "failed_checks": 0,
    "warnings": 0
  },
  "comparison": {
    "baseline_commit": "beec86e8",
    "checks_delta": 0,
    "speedup_percent": 0.0
  }
}
```

---

## 🤖 GitHub Actions: Triggers

### Push to Branches
```bash
git push origin main
git push origin dev
# → Workflow roda automaticamente
```

### Pull Requests
```bash
# Criar PR para main ou dev
# → Workflow roda e comenta no PR com resultados
```

### Manual Trigger
No GitHub:
1. Ir em **Actions** → **Tests and Benchmarks**
2. Clicar **Run workflow**
3. Escolher branch e rodar

---

## 📈 Análise de Performance

### Comparar Dois Commits
```bash
# Comparar commit atual com anterior
git log --oneline -2
# abc1234 feat: ONDA 5E
# def5678 feat: ONDA 5D

# Ver benchmark de cada commit
jq '{commit, tests_passed, duration_seconds}' benchmark_abc1234.json
jq '{commit, tests_passed, duration_seconds}' benchmark_def5678.json
```

### Tendências ao Longo do Tempo
```bash
# Extrair duração de todos os benchmarks
jq -r '.smoke_tests.duration_seconds' benchmark_*.json | \
  awk '{sum+=$1; count++} END {print "Média:", sum/count, "s"}'

# Ver commits com mais de 5s de testes
jq -r 'select(.smoke_tests.duration_seconds > 5) | .commit' benchmark_*.json
```

---

## 🛡️ Linting no CI

### Black (Formatação)
```bash
# Localmente
black --check --line-length 120 .

# No CI: falha se código não estiver formatado
```

### Ruff (Linting)
```bash
# Localmente
ruff check .

# No CI: falha se houver erros E, W, F, I, C, B
```

### MyPy (Type Checking)
```bash
# Localmente
mypy pinterest_board_dl.py

# No CI: falha se houver erros de tipo
```

---

## 📦 Artifacts no CI

### Download de Artifacts
No GitHub Actions:
1. Ir em **Actions** → workflow run
2. Scroll até **Artifacts**
3. Download `benchmark-results`

### Conteúdo do Artifact
```
benchmark_1768191683.json
```

---

## 🔧 Customização

### Adicionar Novo Benchmark
Editar `benchmark.py`:
```python
def run_custom_benchmark(self):
    """Seu benchmark customizado."""
    start = time.time()
    # ... código ...
    duration = time.time() - start
    return {"custom_metric": duration}
```

### Adicionar Step no Workflow
Editar `.github/workflows/tests.yml`:
```yaml
- name: Custom Check
  run: |
    python3 custom_script.py
```

---

## 📊 Exemplos de Uso no PR

### Comentário Automático no PR
```markdown
## 🎯 Benchmark Results

**Commit:** abc1234
**Smoke Tests:** ✅ 11/11 PASS (3.0s)
**Diagnostics:** 0 checks

**Comparison with baseline:**
- ✅ No regressions detected
- ⚡ Speedup: 0% (no changes)
```

---

## 🎓 Benefícios

| Benefício | Descrição |
|-----------|-----------|
| ✅ **Testes Automáticos** | 11 testes rodando em 3 versões Python |
| 📊 **Benchmarks Persistentes** | Histórico completo via artifacts |
| 🔍 **Comparação de Baselines** | Detecta regressões automaticamente |
| 💬 **PR Comments** | Resultados publicados em PRs |
| 🛡️ **Lint Enforced** | Black + Ruff + MyPy no CI |

---

## 🐛 Troubleshooting

### Benchmark Falhando Localmente
```bash
# Verificar se diagnostics.py existe
ls -l diagnostics.py

# Rodar testes manualmente
python -m pytest tests/ -q

# Verificar git history
git log --oneline -5
```

### Workflow Falhando no CI
```bash
# Ver logs no GitHub Actions
# Verificar se requirements.txt está atualizado
cat requirements.txt | grep -E "psutil|playwright"

# Testar localmente com mesma versão Python
python3 --version
python3 -m pip install -r requirements.txt
python -m pytest tests/ -q
```

---

**Guia criado em:** 12 de janeiro de 2026  
**Versão:** 1.0.0  
**Autor:** GitHub Copilot
