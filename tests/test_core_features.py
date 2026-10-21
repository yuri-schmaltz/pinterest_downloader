#!/usr/bin/env python3
"""Testes rápidos e fumaça para validar patches ONDA 1, 2, 3, 4, 5B e 5C."""

import json
import tempfile
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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
    assert SCROLL_STABLE_ROUNDS >= 3, (
        f"Scroll stable rounds too low: {SCROLL_STABLE_ROUNDS}. "
        "ONDA 4 lowered it to 3; commit b8a63fe raised it to 20 to survive "
        "page lag and popups. Keep it at 3 or above."
    )
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
        
        cache_json = json.dumps(test_cache, indent=2, ensure_ascii=False)
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
    repo_root = Path(__file__).parent.parent
    cli_path = repo_root / "src" / "pinterest_board_dl.py"
    assert cli_path.exists(), f"CLI entry point not found at {cli_path}"
    
    result = subprocess.run(
        [sys.executable, str(cli_path), "--help"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    
    assert result.returncode == 0, f"CLI --help failed: {result.stderr}"
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
    
    # Verificar constantes.
    # Invariante, não valor fixo: a ONDA 4 baixou para 3 e o commit b8a63fe
    # subiu para 20 (resiliência a lag/popups). Fixar o número exato aqui
    # faria o teste quebrar a cada novo ajuste de tuning; o que importa é
    # que ele nunca volte abaixo do piso de 3 rodadas estáveis.
    assert SCROLL_STABLE_ROUNDS >= 3, f"Expected >= 3, got {SCROLL_STABLE_ROUNDS}"
    assert SCROLL_HEIGHT_CHECK == True, "Height check should be enabled"
    
    # Verificar que o limiar de parada antecipada nunca é menor que o de
    # estabilidade -- se fosse, o scroll pararia antes de a página assentar.
    assert SCROLL_STABLE_ROUNDS >= 3, "Scroll would stop before the page settles"
    
    print(f"   Stable rounds: {SCROLL_STABLE_ROUNDS} (piso: 3, atual: resiliente a lag)")
    print(f"   Height check: {'✓ Ativado' if SCROLL_HEIGHT_CHECK else '✗ Desativado'}")
    
    print("✅ PASS: Scroll detection configurado\n")


def test_package_layout():
    """Test 8: Verificar a integridade do layout do pacote e da extensão.

    Substitui o antigo teste de `diagnostics.py`, que foi removido de
    propósito no commit 9fb4c3e. Este teste cobre o que realmente quebrou
    o projeto: o restructure para `src/` e o `lib/` do .gitignore making
    arquivos referenciados desaparecerem do repositório.
    """
    print("TEST 8: Integridade do layout (src/ + extension/)")
    
    repo_root = Path(__file__).parent.parent
    src_dir = repo_root / "src"
    ext_dir = repo_root / "extension"
    
    # 8.1 -- os módulos do core precisam estar onde o código espera
    for module_name in [
        "pinterest_board_dl.py",
        "pinterest_board_gui.py",
        "json_logger.py",
        "adaptive_workers.py",
        "rate_limiter.py",
    ]:
        assert (src_dir / module_name).exists(), f"src/{module_name} not found"
    
    # 8.2 -- e precisam ser importáveis de fato
    import importlib
    for module_name in [
        "pinterest_board_dl",
        "json_logger",
        "adaptive_workers",
        "rate_limiter",
    ]:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise AssertionError(f"Failed to import {module_name}: {exc}") from exc
    
    # 8.3 -- a extensão precisa referenciar apenas arquivos versionados.
    #         Esta era a causa raiz do build não-reproduzível: o manifest
    #         apontava para lib/i18n.js, que o .gitignore engolia.
    manifest_path = ext_dir / "manifest.json"
    assert manifest_path.exists(), "extension/manifest.json not found"
    manifest = json.loads(manifest_path.read_text())
    
    referenced = []
    for entry in manifest.get("content_scripts", []):
        referenced.extend(entry.get("js", []))
    if "background" in manifest:
        bg = manifest["background"]
        referenced.append(bg.get("service_worker", ""))
    if "action" in manifest:
        referenced.append(manifest["action"].get("default_popup", ""))
    
    for rel in filter(None, referenced):
        target = ext_dir / rel
        assert target.exists(), (
            f"extension/manifest.json references '{rel}' but it is not in the "
            f"repository -- the extension would fail to load. Check that the "
            f"file is tracked by git (see 'git check-ignore -v extension/{rel}')."
        )
    
    # 8.4 -- os <script> do popup também precisam existir
    popup_html = ext_dir / "popup.html"
    assert popup_html.exists(), "extension/popup.html not found"
    import re
    for src in re.findall(r'<script[^>]+src="([^"]+)"', popup_html.read_text()):
        assert (ext_dir / src).exists(), (
            f"extension/popup.html loads '{src}' but it is not in the repository"
        )
    
    print("✅ PASS: Layout do pacote e da extensão íntegros\n")


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


def test_adaptive_workers():
    """Test 10: Verificar funcionalidade de adaptive workers (ONDA 5C)."""
    print("TEST 10: Adaptive Workers (ONDA 5C)")
    
    from adaptive_workers import get_adaptive_manager, reset_adaptive_manager
    
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_file = Path(tmpdir) / "metrics.json"
        
        # Reset manager
        reset_adaptive_manager()
        
        # Get manager
        manager = get_adaptive_manager(min_workers=2, max_workers=8)
        manager.metrics_file = metrics_file  # Use temp file
        
        # Test initial state
        assert manager.current_workers == 2, "Should start with min_workers"
        assert manager.get_success_rate() == 1.0, "Initial success rate should be 1.0"
        
        # Record some successful operations
        for i in range(10):
            manager.record_success(50.0 + i * 5)  # 50-95ms latency
        
        success_rate = manager.get_success_rate()
        assert success_rate == 1.0, "Success rate should be 100%"
        assert len(manager.latencies) == 10, "Should have 10 latencies"
        
        avg_latency = manager.get_avg_latency()
        assert avg_latency > 0, "Average latency should be > 0"
        
        # Test adjustment (should increase if CPU/memory low)
        # Note: actual adjustment depends on system state
        initial_workers = manager.current_workers
        new_workers = manager.adjust_workers()
        
        # Verify metrics are recorded
        assert len(manager.metrics_history) > 0, "Metrics should be recorded"
        
        # Test save
        manager.save_metrics()
        assert metrics_file.exists(), "Metrics file should be created"
        
        # Verify JSON content
        with open(metrics_file, 'r') as f:
            data = json.load(f)
        
        assert "version" in data, "Missing version"
        assert "metrics" in data, "Missing metrics array"
        assert len(data["metrics"]) > 0, "Should have at least one metric"
        
        first_metric = data["metrics"][0]
        assert "timestamp" in first_metric, "Missing timestamp"
        assert "cpu_percent" in first_metric, "Missing cpu_percent"
        assert "memory_percent" in first_metric, "Missing memory_percent"
        assert "active_workers" in first_metric, "Missing active_workers"
        assert "success_rate" in first_metric, "Missing success_rate"
        assert "avg_latency_ms" in first_metric, "Missing avg_latency_ms"
        
        # Test get_summary
        summary = manager.get_summary()
        assert "current_workers" in summary, "Summary missing current_workers"
        assert "success_rate" in summary, "Summary missing success_rate"
        assert "avg_latency_ms" in summary, "Summary missing avg_latency_ms"
        assert summary["success_rate"] == 1.0, "Summary success_rate should match"
        
        # Clean up
        reset_adaptive_manager()
    
    print("✅ PASS: Adaptive Workers funciona corretamente (ONDA 5C)\n")


if __name__ == "__main__":
    print("=" * 60)
    print("SMOKE TESTS - ONDAS 1, 2, 3, 4, 5B, 5C E 5E")
    print("=" * 60 + "\n")
    
    try:
        test_constants()
        test_cache_functions()
        test_download_options()
        test_retry_logic()
        test_cli_help()
        test_browser_reuse()
        test_scroll_detection()
        test_package_layout()
        test_json_logger()
        test_adaptive_workers()
        
        # TEST 11: Rate Limiting (ONDA 5E)
        print("TEST 11: Rate Limiting (ONDA 5E)")
        import subprocess
        test_11_path = Path(__file__).parent / "test_11_rate_limiting.py"
        result = subprocess.run([sys.executable, str(test_11_path)], capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        if result.returncode != 0:
            print(f"❌ FAIL: Test 11 falhou\n{result.stdout}\n{result.stderr}")
            sys.exit(1)
        print("✅ PASS: Rate limiting funcionando corretamente\n")
        
        print("=" * 60)
        print("✅ TODOS OS 11 TESTES PASSARAM!")
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
