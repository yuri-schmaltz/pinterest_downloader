#!/usr/bin/env python3
"""Script de benchmarking para comparar performance entre versões.

ONDA 5D - CI Benchmarks
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List


class BenchmarkRunner:
    """Executa benchmarks e compara com baseline."""
    
    def __init__(self, baseline_file: str = "diagnostics_baseline.json"):
        self.baseline_file = Path(baseline_file)
        self.results: Dict = {}
        self.timestamp = datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
    
    def run_diagnostics(self) -> Dict:
        """Executa diagnostics.py e captura resultado."""
        print("🔍 Executando diagnostics.py...")
        
        try:
            result = subprocess.run(
                [sys.executable, "diagnostics.py"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode == 0:
                print("✅ Diagnostics completo")
                
                # Carregar JSON gerado
                if self.baseline_file.exists():
                    data = json.loads(self.baseline_file.read_text())
                    return data
                else:
                    print("⚠️  Arquivo baseline não encontrado")
                    return {}
            else:
                print(f"❌ Diagnostics falhou: {result.stderr}")
                return {}
        
        except subprocess.TimeoutExpired:
            print("❌ Diagnostics timeout (>60s)")
            return {}
        except Exception as e:
            print(f"❌ Erro ao executar diagnostics: {e}")
            return {}
    
    def run_smoke_tests(self) -> Dict:
        """Executa test_patches.py e captura resultado."""
        print("\n🧪 Executando testes de smoke...")
        
        try:
            start_time = time.time()
            result = subprocess.run(
                [sys.executable, "test_patches.py"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            duration = time.time() - start_time
            
            if result.returncode == 0:
                # Contar testes passados
                passed = result.stdout.count("✅ PASS")
                print(f"✅ {passed} testes passaram em {duration:.1f}s")
                
                return {
                    "passed": passed,
                    "duration_seconds": duration,
                    "output": result.stdout[-500:],  # últimas 500 chars
                }
            else:
                print(f"❌ Testes falharam")
                return {
                    "passed": 0,
                    "duration_seconds": duration,
                    "error": result.stdout[-500:],
                }
        
        except subprocess.TimeoutExpired:
            print("❌ Testes timeout (>120s)")
            return {"passed": 0, "duration_seconds": 120, "error": "Timeout"}
        except Exception as e:
            print(f"❌ Erro ao executar testes: {e}")
            return {"passed": 0, "duration_seconds": 0, "error": str(e)}
    
    def load_baseline(self) -> Dict:
        """Carrega baseline anterior."""
        if not self.baseline_file.exists():
            return {}
        
        try:
            return json.loads(self.baseline_file.read_text())
        except Exception:
            return {}
    
    def compare_with_baseline(self, current: Dict, baseline: Dict) -> None:
        """Compara resultados atuais com baseline."""
        if not baseline:
            print("\n⚠️  Nenhum baseline anterior encontrado")
            print("   Esta será a primeira execução de referência")
            return
        
        print("\n📊 COMPARAÇÃO COM BASELINE")
        print("=" * 60)
        
        # Comparar checks
        curr_passed = current.get("passed_checks", 0)
        base_passed = baseline.get("passed_checks", 0)
        
        if curr_passed == base_passed:
            print(f"✅ Checks: {curr_passed}/{current.get('total_checks', 0)} (sem mudanças)")
        elif curr_passed > base_passed:
            diff = curr_passed - base_passed
            print(f"📈 Checks: {curr_passed}/{current.get('total_checks', 0)} (+{diff} vs baseline)")
        else:
            diff = base_passed - curr_passed
            print(f"📉 Checks: {curr_passed}/{current.get('total_checks', 0)} (-{diff} vs baseline)")
        
        # Comparar performance
        curr_perf = current.get("performance_summary", {})
        base_perf = baseline.get("performance_summary", {})
        
        curr_speedup = curr_perf.get("total_speedup_percent", 0)
        base_speedup = base_perf.get("total_speedup_percent", 0)
        
        if abs(curr_speedup - base_speedup) < 1:
            print(f"⚡ Speedup: {curr_speedup}% (sem mudanças)")
        elif curr_speedup > base_speedup:
            diff = curr_speedup - base_speedup
            print(f"🚀 Speedup: {curr_speedup}% (+{diff:.1f}% vs baseline)")
        else:
            diff = base_speedup - curr_speedup
            print(f"⚠️  Speedup: {curr_speedup}% (-{diff:.1f}% vs baseline)")
        
        # Comparar ONDAS
        curr_ondas = curr_perf.get("ondas", {})
        base_ondas = base_perf.get("ondas", {})
        
        new_ondas = set(curr_ondas.keys()) - set(base_ondas.keys())
        if new_ondas:
            print(f"\n🆕 Novas ONDAS: {', '.join(sorted(new_ondas))}")
            for onda in sorted(new_ondas):
                print(f"   {onda}: {curr_ondas[onda].get('speedup_percent', 0)}%")
    
    def generate_report(self) -> Dict:
        """Gera relatório completo de benchmark."""
        print("\n" + "=" * 60)
        print("📊 BENCHMARK REPORT")
        print("=" * 60)
        
        # Executar diagnostics
        diagnostics = self.run_diagnostics()
        
        # Executar testes
        tests = self.run_smoke_tests()
        
        # Carregar baseline
        baseline = self.load_baseline()
        
        # Comparar
        if diagnostics:
            self.compare_with_baseline(diagnostics, baseline)
        
        # Montar relatório
        report = {
            "benchmark_timestamp": self.timestamp,
            "git_commit": self._get_git_commit(),
            "diagnostics": diagnostics,
            "smoke_tests": tests,
            "baseline_comparison": {
                "baseline_exists": bool(baseline),
                "baseline_timestamp": baseline.get("timestamp", "unknown"),
            }
        }
        
        # Salvar relatório
        report_file = Path(f"benchmark_{int(time.time())}.json")
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\n💾 Relatório salvo em: {report_file}")
        
        return report
    
    def _get_git_commit(self) -> str:
        """Obtém hash do commit atual."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"
    
    def print_summary(self, report: Dict) -> None:
        """Imprime sumário do benchmark."""
        print("\n" + "=" * 60)
        print("✅ BENCHMARK SUMMARY")
        print("=" * 60)
        
        tests = report.get("smoke_tests", {})
        diag = report.get("diagnostics", {})
        
        print(f"\n🧪 Smoke Tests:")
        print(f"   Passed: {tests.get('passed', 0)}")
        print(f"   Duration: {tests.get('duration_seconds', 0):.1f}s")
        
        if diag:
            print(f"\n🔍 Diagnostics:")
            print(f"   Checks: {diag.get('passed_checks', 0)}/{diag.get('total_checks', 0)}")
            
            perf = diag.get("performance_summary", {})
            if perf:
                print(f"   Speedup: {perf.get('total_speedup_percent', 0)}%")
        
        print(f"\n📦 Git Commit: {report.get('git_commit', 'unknown')[:8]}")
        print(f"⏰ Timestamp: {report.get('benchmark_timestamp', 'unknown')}")


def main():
    """Main entry point."""
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  🎯 BENCHMARK RUNNER - ONDA 5D".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "═" * 58 + "╝")
    
    runner = BenchmarkRunner()
    
    try:
        report = runner.generate_report()
        runner.print_summary(report)
        
        print("\n✅ Benchmark completo!")
        sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n⚠️  Benchmark interrompido")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
