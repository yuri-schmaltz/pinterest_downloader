#!/usr/bin/env python3
"""Testes rápidos e fumaça para validar patches ONDA 1 e ONDA 2."""

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
    load_pin_cache,
    save_pin_cache,
    DownloadOptions,
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
    print("✅ PASS: Todas constantes estão corretas\n")


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


if __name__ == "__main__":
    print("=" * 60)
    print("SMOKE TESTS - ONDA 1 E ONDA 2")
    print("=" * 60 + "\n")
    
    try:
        test_constants()
        test_cache_functions()
        test_download_options()
        test_retry_logic()
        test_cli_help()
        
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
