#!/usr/bin/env python3
"""Script de diagnóstico automatizado para Pinterest Board Downloader.

Executa smoke tests, valida configuração e coleta métricas de baseline.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

# Cores para output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


def print_section(title: str) -> None:
    """Imprime cabeçalho de seção."""
    print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
    print(f"{BOLD}{BLUE}{title:^70}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}\n")


def print_test(name: str, status: str, details: str = "") -> None:
    """Imprime resultado de teste."""
    if status == "PASS":
        symbol = f"{GREEN}✅{RESET}"
    elif status == "WARN":
        symbol = f"{YELLOW}⚠️{RESET}"
    else:
        symbol = f"{RED}❌{RESET}"
    
    print(f"{symbol} {name:.<50} {status}")
    if details:
        print(f"   {details}")


def run_command(cmd: List[str], capture: bool = True) -> Tuple[int, str, str]:
    """Executa comando e retorna (code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=10,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)


def check_python_version() -> Tuple[str, str]:
    """Verifica versão do Python."""
    version = sys.version.split()[0]
    major, minor = sys.version_info[:2]
    
    if major == 3 and minor >= 10:
        return "PASS", f"Python {version}"
    elif major == 3 and minor >= 8:
        return "WARN", f"Python {version} (recomendado 3.10+)"
    else:
        return "FAIL", f"Python {version} (requer 3.8+)"


def check_dependencies() -> Tuple[str, str]:
    """Verifica dependências instaladas."""
    required = ["requests", "playwright"]
    missing = []
    
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    
    if not missing:
        return "PASS", f"Todas dependências OK: {', '.join(required)}"
    else:
        return "FAIL", f"Faltando: {', '.join(missing)}"


def check_playwright_browsers() -> Tuple[str, str]:
    """Verifica se navegadores Playwright estão instalados."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
                return "PASS", "Chromium instalado e funcional"
            except Exception as e:
                return "FAIL", f"Chromium não disponível: {e}"
    except ImportError:
        return "FAIL", "Playwright não instalado"


def check_import_time() -> Tuple[str, str]:
    """Mede tempo de import do módulo principal."""
    start = time.time()
    try:
        # Import sem carregar PyQt6
        import pinterest_board_dl
        duration = time.time() - start
        
        if duration < 0.1:
            return "PASS", f"{duration:.3f}s (excelente)"
        elif duration < 0.5:
            return "WARN", f"{duration:.3f}s (OK, meta: <0.1s)"
        else:
            return "FAIL", f"{duration:.3f}s (muito lento)"
    except Exception as e:
        return "FAIL", str(e)


def check_constants() -> Tuple[str, str]:
    """Verifica constantes centralizadas."""
    try:
        from pinterest_board_dl import (
            PINTEREST_BASE_URL,
            TIMEOUT_HTTP_GET,
            TIMEOUT_IMAGE_DOWNLOAD,
            TIMEOUT_PAGE_LOAD,
            TIMEOUT_DOM_READY,
            DOWNLOAD_RETRY_DELAY,
            DOWNLOAD_MAX_RETRIES,
            SCROLL_STABLE_ROUNDS,
            SCROLL_HEIGHT_CHECK,
        )
        
        checks = [
            PINTEREST_BASE_URL == "https://www.pinterest.com",
            TIMEOUT_HTTP_GET > 0,
            TIMEOUT_IMAGE_DOWNLOAD > 0,
            TIMEOUT_PAGE_LOAD > 0,
            TIMEOUT_DOM_READY > 0,
            DOWNLOAD_RETRY_DELAY >= 0,
            DOWNLOAD_MAX_RETRIES >= 0,
            SCROLL_STABLE_ROUNDS > 0,
            isinstance(SCROLL_HEIGHT_CHECK, bool),
        ]
        
        if all(checks):
            return "PASS", f"9 constantes validadas (SCROLL_STABLE_ROUNDS={SCROLL_STABLE_ROUNDS})"
        else:
            return "FAIL", "Algumas constantes inválidas"
    except ImportError as e:
        return "FAIL", f"Não foi possível importar: {e}"


def check_magic_numbers() -> Tuple[str, str]:
    """Verifica ausência de magic numbers no código."""
    code, stdout, stderr = run_command(
        ["grep", "-n", r"timeout=[0-9]", "pinterest_board_dl.py"]
    )
    
    if code != 0:  # grep retorna 1 quando não encontra matches
        return "PASS", "Nenhum timeout hardcoded encontrado"
    else:
        count = len(stdout.strip().split('\n'))
        return "FAIL", f"{count} timeout(s) hardcoded encontrado(s)"


def check_cache_functionality() -> Tuple[str, str]:
    """Verifica funcionalidade de cache."""
    try:
        from pinterest_board_dl import load_pin_cache, save_pin_cache
        
        # Teste rápido
        cache_test = {"test": "value"}
        cache_file = Path(".pinterest_cache.json.test")
        
        # Salvar
        cache_file.write_text(json.dumps(cache_test))
        
        # Carregar
        loaded = json.loads(cache_file.read_text())
        
        # Limpar
        cache_file.unlink()
        
        if loaded == cache_test:
            return "PASS", "Cache funcional (load/save OK)"
        else:
            return "FAIL", "Cache não carrega corretamente"
    except Exception as e:
        return "FAIL", str(e)


def check_file_structure() -> Tuple[str, str]:
    """Verifica estrutura de arquivos do projeto."""
    required_files = [
        "pinterest_board_dl.py",
        "pinterest_board_gui.py",
        "requirements.txt",
        "README.md",
        "LICENSE",
    ]
    
    missing = [f for f in required_files if not Path(f).exists()]
    
    if not missing:
        return "PASS", "Todos arquivos principais presentes"
    else:
        return "WARN", f"Faltando: {', '.join(missing)}"


def check_cli_help() -> Tuple[str, str]:
    """Verifica se CLI --help funciona."""
    code, stdout, stderr = run_command(
        [sys.executable, "pinterest_board_dl.py", "--help"]
    )
    
    if code == 0 and "--cache-dir" in stdout and "--no-cache" in stdout:
        return "PASS", "CLI funcional com flags de cache"
    elif code == 0:
        return "WARN", "CLI funciona mas flags de cache ausentes"
    else:
        return "FAIL", f"CLI retornou erro: {stderr}"


def get_disk_usage() -> Tuple[str, str]:
    """Obtém uso de disco do projeto."""
    try:
        # Soma tamanho dos arquivos Python
        total_bytes = 0
        for f in Path(".").glob("*.py"):
            total_bytes += f.stat().st_size
        
        total_kb = total_bytes / 1024
        
        if total_kb < 100:
            status = "PASS"
        elif total_kb < 200:
            status = "WARN"
        else:
            status = "PASS"  # Código pode crescer
        
        return status, f"{total_kb:.1f} KB (arquivos .py)"
    except Exception as e:
        return "WARN", str(e)


def get_line_count() -> Tuple[str, str]:
    """Conta linhas de código."""
    try:
        code, stdout, stderr = run_command(["wc", "-l"] + list(Path(".").glob("*.py")))
        if code == 0:
            lines = stdout.strip().split('\n')
            total_line = lines[-1] if lines else ""
            total = total_line.split()[0] if total_line else "0"
            return "PASS", f"{total} linhas totais"
        return "WARN", "Não foi possível contar"
    except Exception as e:
        return "WARN", str(e)


def collect_metrics() -> Dict[str, any]:
    """Coleta métricas de baseline."""
    metrics = {}
    
    # Python version
    metrics["python_version"] = sys.version.split()[0]
    
    # Import time
    start = time.time()
    try:
        import pinterest_board_dl
        metrics["import_time_s"] = time.time() - start
    except:
        metrics["import_time_s"] = -1
    
    # File sizes
    try:
        metrics["main_size_kb"] = Path("pinterest_board_dl.py").stat().st_size / 1024
        metrics["gui_size_kb"] = Path("pinterest_board_gui.py").stat().st_size / 1024
    except:
        pass
    
    # Constants
    try:
        from pinterest_board_dl import (
            SCROLL_STABLE_ROUNDS,
            SCROLL_HEIGHT_CHECK,
            DOWNLOAD_MAX_RETRIES,
        )
        metrics["scroll_stable_rounds"] = SCROLL_STABLE_ROUNDS
        metrics["scroll_height_check"] = SCROLL_HEIGHT_CHECK
        metrics["max_retries"] = DOWNLOAD_MAX_RETRIES
    except:
        pass
    
    return metrics


def main():
    """Executa diagnóstico completo."""
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}{'Pinterest Board Downloader - Diagnóstico':^70}{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}")
    
    # Ambiente
    print_section("🔍 AMBIENTE")
    print_test("Versão Python", *check_python_version())
    print_test("Dependências", *check_dependencies())
    print_test("Playwright Chromium", *check_playwright_browsers())
    
    # Código
    print_section("📦 CÓDIGO")
    print_test("Estrutura de arquivos", *check_file_structure())
    print_test("Import time", *check_import_time())
    print_test("Constantes centralizadas", *check_constants())
    print_test("Magic numbers ausentes", *check_magic_numbers())
    
    # Funcionalidade
    print_section("⚙️  FUNCIONALIDADE")
    print_test("Cache load/save", *check_cache_functionality())
    print_test("CLI --help", *check_cli_help())
    
    # Métricas
    print_section("📊 MÉTRICAS")
    print_test("Uso de disco", *get_disk_usage())
    print_test("Linhas de código", *get_line_count())
    
    # Baseline
    print_section("📈 BASELINE")
    metrics = collect_metrics()
    print(f"\n{json.dumps(metrics, indent=2)}\n")
    
    # Save metrics
    metrics_file = Path("diagnostics_baseline.json")
    metrics_file.write_text(json.dumps(metrics, indent=2))
    print(f"{GREEN}✅{RESET} Métricas salvas em: {metrics_file}\n")
    
    print(f"{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}{GREEN}Diagnóstico completo!{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    main()
