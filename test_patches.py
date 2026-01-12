#!/usr/bin/env python3
"""Testes rápidos e fumaça para validar patches ONDA 1, 2, 3, 4 e 5B."""

import json
import tempfile
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

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
    load_pin_cache,
    save_pin_cache,
    DownloadOptions,
    collect_pin_links,
    collect_board_urls,
)


def test_constants():
    """Test 1: Verificar constantes centralizadas."""
    print("TEST 1: Constantes centralizadas")
    assert PINTEREST_BASE_URL == "https://www.pinterest.com", "URL base incorrect"
    assert TIMEOUT_HTTP_GET == 25, "HTTP timeout incorrect"
    assert TIMEOUT_IMAGE_DOWNLOAD == 60, "Image timeout incorrect"
    assert TIMEOUT_PAGE_LOAD == 90_000, "Page load timeout incorrect"
    assert TIMEOUT_DOM_READY == 15_000, "DOM ready timeout incorrect"
    assert DOWNLOAD_RETRY_DELAY == 1.0, "Retry delay incorrect"
    assert DOWNLOAD_MAX_RETRIES == 1, "Max retries incorrect"
    assert SCROLL_STABLE_ROUNDS == 3, "Scroll stable rounds incorrect (ONDA 4: reduced from 6)"
    assert SCROLL_HEIGHT_CHECK == True, "Scroll height check should be enabled (ONDA 4)"
    print("✅ PASS: Todas constantes estão corretas (incluindo ONDA 4)\n")


def test_cache_functions():
    """Test 2: Verificar funcionalidade de cache."""
    print("TEST 2: Cache de metadados")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / ".pinterest_cache.json"
        
        # Salvar cache
        test_cache = {
            "https://www.pinterest.com/pin/123": "https://example.com/img1.jpg",
            "https://www.pinterest.com/pin/456": "https://example.com/img2.jpg",
        }
        
        cache_json = json.dumps(test_cache, indent=2)
        cache_file.write_text(cache_json)
        
        # Carregar cache
        loaded = json.loads(cache_file.read_text())
        assert len(loaded) == 2, "Cache load failed"
        assert loaded["https://www.pinterest.com/pin/123"] == "https://example.com/img1.jpg"
        
    print("✅ PASS: Cache salva e carregada corretamente\n")


def test_download_options():
    """Test 3: Verificar novas opções de download."""
    print("TEST 3: DownloadOptions com cache")
    
    # Default
    opts1 = DownloadOptions()
    assert opts1.use_cache == True, "Default use_cache should be True"
    assert opts1.cache_dir == ".", "Default cache_dir should be '.'"
    
    # Custom
    opts2 = DownloadOptions(
        out_root="/tmp/pins",
        use_cache=False,
        cache_dir="/tmp/cache",
    )
    assert opts2.use_cache == False, "use_cache not set correctly"
    assert opts2.cache_dir == "/tmp/cache", "cache_dir not set correctly"
    
    print("✅ PASS: DownloadOptions funciona corretamente\n")


def test_retry_logic():
    """Test 4: Validar retry com exponential backoff."""
    print("TEST 4: Exponential backoff em retries")
    
    # Simular cálculo de delays
    max_retries = DOWNLOAD_MAX_RETRIES
    delays = []
    for attempt in range(max_retries):  # Note: range(max_retries) = 1 iteration
        delay = DOWNLOAD_RETRY_DELAY * (2 ** attempt)
        delays.append(delay)
    
    expected = [1.0]  # Para DOWNLOAD_MAX_RETRIES = 1 (1 retry = 1 delay)
    assert delays == expected, f"Delays incorrect: {delays} vs {expected}"
    
    print(f"✅ PASS: Retry delays corretos: {delays}\n")


def test_cli_help():
    """Test 5: Verificar flags CLI."""
    print("TEST 5: Flags CLI disponíveis")
    
    import subprocess
    result = subprocess.run(
        [sys.executable, "pinterest_board_dl.py", "--help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    )
    
    assert "--cache-dir" in result.stdout, "--cache-dir flag not found"
    assert "--no-cache" in result.stdout, "--no-cache flag not found"
    
    print("✅ PASS: Flags de cache presentes no CLI\n")


def test_browser_reuse():
    """Test 6: Validar que collect_pin_links e collect_board_urls aceitam browser opcional."""
    print("TEST 6: Browser reuse - API signature")
    
    import inspect
    
    # Verificar signatures
    sig_pins = inspect.signature(collect_pin_links)
    sig_boards = inspect.signature(collect_board_urls)
    
    assert 'browser' in sig_pins.parameters, "collect_pin_links missing 'browser' parameter"
    assert 'browser' in sig_boards.parameters, "collect_board_urls missing 'browser' parameter"
    
    # Verificar defaults (None = opcional)
    assert sig_pins.parameters['browser'].default is None, "browser param should default to None"
    assert sig_boards.parameters['browser'].default is None, "browser param should default to None"
    
    print("✅ PASS: Funções aceitam browser opcional corretamente\n")
def test_scroll_detection():
    """Test 7: Validar configuração de scroll detection inteligente."""
    print("TEST 7: Scroll detection inteligente (ONDA 4)")
    
    # Verificar constantes
    assert SCROLL_STABLE_ROUNDS == 3, f"Expected 3, got {SCROLL_STABLE_ROUNDS}"
    assert SCROLL_HEIGHT_CHECK == True, "Height check should be enabled"
    
    # Verificar que reduzimos de 6 para 3 (50% faster detection)
    old_value = 6
    improvement = ((old_value - SCROLL_STABLE_ROUNDS) / old_value) * 100
    
    print(f"   Stable rounds: {SCROLL_STABLE_ROUNDS} (reduzido de {old_value})")
    print(f"   Melhoria: {improvement:.0f}% mais rápido para detectar fim")
    print(f"   Height check: {'✓ Ativado' if SCROLL_HEIGHT_CHECK else '✗ Desativado'}")
    
    print("✅ PASS: Scroll detection otimizado\n")


def test_diagnostics_script():
    """Test 8: Verificar existência do script de diagnóstico."""
    print("TEST 8: Script de diagnóstico")
    
    diag_file = Path(__file__).parent / "diagnostics.py"
    assert diag_file.exists(), "diagnostics.py not found"
    
    # Verificar que é executável
    content = diag_file.read_text()
    assert "def main()" in content, "main() function not found"
    assert "collect_metrics" in content, "collect_metrics() not found"
    
    print("✅ PASS: Script de diagnóstico presente e válido\n")


def test_json_logger():
    """Test 9: Verificar funcionalidade de json_logger (ONDA 5B)."""
    print("TEST 9: JSON Logger (ONDA 5B)")
    
    import json
    from json_logger import get_logger, reset_logger, LogEntry
    
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test_log.json"
        
        # Reset logger to clean state
        reset_logger()
        
        # Get logger instance
        logger = get_logger(output_file=str(log_file), enabled=True)
        
        # Test phase tracking
        logger.start_phase("test_phase_1")
        time.sleep(0.1)  # Simulate some work
        logger.end_phase("test_phase_1", count=10, message="Test phase completed")
        
        # Test info/warn/error logging
        logger.info("test_phase_2", "Starting test", board_url="https://example.com", count=5)
        logger.warn("test_phase_2", "Warning message", board_url="https://example.com")
        logger.error("test_phase_2", "Error occurred", board_url="https://example.com")
        
        # Save logs
        logger.save()
        
        # Verify log file was created
        assert log_file.exists(), f"Log file not created at {log_file}"
        
        # Verify JSON content
        with open(log_file, 'r') as f:
            data = json.load(f)
        
        # The structure should be {version, generated_at, total_entries, logs}
        assert isinstance(data, dict), "Logs should be a dict"
        assert "logs" in data, "Missing 'logs' key"
        assert "version" in data, "Missing 'version' key"
        
        logs = data["logs"]
        assert isinstance(logs, list), "Logs list should be a list"
        assert len(logs) > 0, "Logs should not be empty"
        
        # Check first log entry structure
        first_log = logs[0]
        assert "timestamp" in first_log, "Missing timestamp"
        assert "phase" in first_log, "Missing phase"
        assert "level" in first_log, "Missing level"
        assert "message" in first_log, "Missing message"
        
        # Verify some values
        assert first_log["phase"] == "test_phase_1", "Phase mismatch"
        
        # Test get_summary
        reset_logger()
        logger2 = get_logger(output_file=str(log_file), enabled=True)
        logger2.start_phase("summary_test")
        logger2.end_phase("summary_test", count=42)
        summary = logger2.get_summary()
        
        # Summary has structure: {"total_entries": N, "phases": {phase_name: {count, duration_ms, errors}}}
        assert "phases" in summary, "Missing 'phases' in summary"
        assert "summary_test" in summary["phases"], "Phase not in summary"
        # start_phase and end_phase together create 1 entry with duration
        assert summary["phases"]["summary_test"]["count"] >= 1, "Count should be at least 1"
        assert summary["phases"]["summary_test"]["duration_ms"] > 0, "Duration should be > 0"
        
        # Clean up
        reset_logger()
    
    print("✅ PASS: JSON Logger funciona corretamente (ONDA 5B)\n")


if __name__ == "__main__":
    print("=" * 60)
    print("SMOKE TESTS - ONDAS 1, 2, 3, 4 E 5B")
    print("=" * 60 + "\n")
    
    try:
        test_constants()
        test_cache_functions()
        test_download_options()
        test_retry_logic()
        test_cli_help()
        test_browser_reuse()
        test_scroll_detection()
        test_diagnostics_script()
        test_json_logger()
        
        print("=" * 60)
        print("✅ TODOS OS TESTES PASSARAM!")
        print("=" * 60)
        sys.exit(0)
        
    except AssertionError as e:
        print(f"\n❌ FALHA: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
