#!/usr/bin/env python3
"""
TEST 11 - Rate Limiting (ONDA 5E)
Valida o sistema de rate limiting inteligente com sliding windows.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rate_limiter import (
    RateLimitConfig,
    get_rate_limiter,
    reset_rate_limiter,
)


def test_rate_limiter_initialization():
    """Testa inicialização do RateLimiter com configuração padrão."""
    reset_rate_limiter()
    limiter = get_rate_limiter()

    assert limiter.config.max_requests_per_second == 5.0, "Default requests/second deve ser 5"
    assert limiter.config.max_requests_per_minute == 200, "Default requests/minute deve ser 200"
    assert limiter.config.max_requests_per_hour == 10000, "Default requests/hour deve ser 10000"
    assert limiter.config.backoff_on_429 == 60.0, "Default backoff inicial deve ser 60s"
    print("✓ Inicialização do rate limiter OK")


def test_rate_limiter_custom_config():
    """Testa inicialização com configuração customizada."""
    reset_rate_limiter()
    custom_config = RateLimitConfig(
        max_requests_per_second=2.0,
        max_requests_per_minute=100,
        max_requests_per_hour=5000,
        backoff_on_429=30.0,
    )
    limiter = get_rate_limiter(custom_config)

    assert limiter.config.max_requests_per_second == 2.0, "Custom requests/second não aplicado"
    assert limiter.config.max_requests_per_minute == 100, "Custom requests/minute não aplicado"
    print("✓ Configuração customizada OK")


def test_rate_limiter_acquire_basic():
    """Testa acquisição básica de permissão para requisição."""
    reset_rate_limiter()
    limiter = get_rate_limiter()

    # Primeira requisição deve ser imediata
    start = time.time()
    result = limiter.acquire(timeout=1.0)
    elapsed = time.time() - start

    assert result is True, "acquire() deve retornar True quando permitido"
    assert elapsed < 0.1, f"Primeira requisição não deve bloquear (levou {elapsed:.3f}s)"
    print("✓ Acquire básico OK")


def test_rate_limiter_sliding_window():
    """Testa sliding window de 1 segundo (5 req/s)."""
    reset_rate_limiter()
    limiter = get_rate_limiter()

    # Fazer 5 requisições rápidas (limite por segundo)
    for _ in range(5):
        limiter.acquire(timeout=1.0)

    # A 6ª requisição deve bloquear até a janela deslizar
    start = time.time()
    result = limiter.acquire(timeout=2.0)
    elapsed = time.time() - start

    assert result is True, "6ª requisição deve ser permitida após sliding window"
    assert elapsed >= 0.8, f"Deveria ter bloqueado pelo menos 0.8s, mas levou {elapsed:.3f}s"
    print("✓ Sliding window (1s) OK")


def test_rate_limiter_report_429():
    """Testa report de erro 429 e exponential backoff."""
    reset_rate_limiter()
    limiter = get_rate_limiter()

    stats_before = limiter.get_stats()
    limiter.report_429()
    stats_after = limiter.get_stats()

    assert stats_after["total_429s"] == stats_before["total_429s"] + 1, "Contador de 429s deve incrementar"
    assert stats_after["backoff_seconds"] == 60.0, "Primeiro backoff deve ser 60s"

    # Segundo 429 deve dobrar o backoff
    limiter.report_429()
    stats_after2 = limiter.get_stats()
    assert stats_after2["backoff_seconds"] == 120.0, "Segundo backoff deve dobrar (120s)"
    print("✓ Report 429 e exponential backoff OK")


def test_rate_limiter_report_success():
    """Testa report de sucesso e gradual backoff reset."""
    reset_rate_limiter()
    limiter = get_rate_limiter()

    # Simular 429 e depois sucessos
    limiter.report_429()
    assert limiter.get_stats()["backoff_seconds"] == 60.0, "Backoff inicial deve ser 60s"

    limiter.report_success()
    stats = limiter.get_stats()
    assert stats["backoff_seconds"] < 60.0, "Backoff deve diminuir após sucesso"
    assert stats["backoff_seconds"] >= 0.0, "Backoff não deve ser negativo"
    print("✓ Report success e backoff reset OK")


def test_rate_limiter_thread_safety():
    """Testa thread-safety com múltiplas threads."""
    reset_rate_limiter()
    limiter = get_rate_limiter()

    results = []
    errors = []

    def worker():
        try:
            for _ in range(3):
                result = limiter.acquire(timeout=5.0)
                results.append(result)
                time.sleep(0.05)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Não deveria ter erros, mas teve: {errors}"
    assert len(results) == 9, f"Deveria ter 9 aquisições (3 threads * 3), mas teve {len(results)}"
    assert all(results), "Todas as aquisições devem ser True"
    print("✓ Thread-safety OK")


def test_rate_limiter_get_stats():
    """Testa obtenção de estatísticas."""
    reset_rate_limiter()
    limiter = get_rate_limiter()

    # Fazer algumas requisições
    limiter.acquire(timeout=1.0)
    limiter.acquire(timeout=1.0)
    limiter.report_429()

    stats = limiter.get_stats()

    assert "total_requests" in stats, "Stats deve conter total_requests"
    assert "total_429s" in stats, "Stats deve conter total_429s"
    assert "backoff_seconds" in stats, "Stats deve conter backoff_seconds"
    assert "window_1s" in stats, "Stats deve conter window_1s"
    assert "window_1m" in stats, "Stats deve conter window_1m"
    assert "window_1h" in stats, "Stats deve conter window_1h"

    assert stats["total_requests"] == 2, f"Total requests deve ser 2, mas é {stats['total_requests']}"
    assert stats["total_429s"] == 1, f"Total 429s deve ser 1, mas é {stats['total_429s']}"
    print("✓ Get stats OK")


def test_rate_limiter_save_stats():
    """Testa salvamento de estatísticas em JSON."""
    import json
    import os

    reset_rate_limiter()
    limiter = get_rate_limiter()

    # Fazer algumas requisições
    limiter.acquire(timeout=1.0)
    limiter.report_429()

    # Salvar stats
    test_file = "test_rate_stats.json"
    limiter.save_stats(test_file)

    # Verificar arquivo
    assert os.path.exists(test_file), f"Arquivo {test_file} não foi criado"

    with open(test_file, "r") as f:
        data = json.load(f)

    assert "total_requests" in data, "JSON deve conter total_requests"
    assert "total_429s" in data, "JSON deve conter total_429s"
    assert data["total_requests"] == 1, "Total requests deve ser 1"
    assert data["total_429s"] == 1, "Total 429s deve ser 1"

    # Cleanup
    os.remove(test_file)
    print("✓ Save stats OK")


def test_rate_limiter_singleton():
    """Testa padrão singleton."""
    reset_rate_limiter()
    limiter1 = get_rate_limiter()
    limiter2 = get_rate_limiter()

    assert limiter1 is limiter2, "get_rate_limiter() deve retornar a mesma instância (singleton)"

    # Modificar estado em limiter1 e verificar em limiter2
    limiter1.report_429()
    stats = limiter2.get_stats()
    assert stats["total_429s"] == 1, "Mudança em limiter1 deve refletir em limiter2 (singleton)"
    print("✓ Singleton pattern OK")


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 11 - Rate Limiting (ONDA 5E)")
    print("=" * 60)

    tests = [
        test_rate_limiter_initialization,
        test_rate_limiter_custom_config,
        test_rate_limiter_acquire_basic,
        test_rate_limiter_sliding_window,
        test_rate_limiter_report_429,
        test_rate_limiter_report_success,
        test_rate_limiter_thread_safety,
        test_rate_limiter_get_stats,
        test_rate_limiter_save_stats,
        test_rate_limiter_singleton,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} FALHOU: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} ERRO: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTADO: {passed} PASS, {failed} FAIL")
    print("=" * 60)

    if failed > 0:
        exit(1)
