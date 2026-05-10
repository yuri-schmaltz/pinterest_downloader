#!/usr/bin/env python3
"""Sistema de rate limiting inteligente para respeitar limites do Pinterest.

ONDA 5E - Rate Limiting
"""

import json
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Deque, Optional


@dataclass
class RateLimitConfig:
    """Configuração de rate limiting."""
    max_requests_per_second: float = 5.0  # Pinterest limit: ~5 req/s
    max_requests_per_minute: int = 200  # Pinterest limit: ~200 req/min
    max_requests_per_hour: int = 10000  # Pinterest limit: ~10k req/h
    backoff_on_429: float = 60.0  # Segundos de espera ao receber 429
    backoff_multiplier: float = 2.0  # Multiplicador de backoff
    max_backoff: float = 300.0  # Máximo 5 minutos de backoff


class RateLimiter:
    """Rate limiter com janelas deslizantes e backoff exponencial."""
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        """Inicializa rate limiter.
        
        Args:
            config: Configuração de rate limiting (usa default se None)
        """
        self.config = config or RateLimitConfig()
        
        # Janelas deslizantes (timestamps de requisições)
        self.requests_1s: Deque[float] = deque()  # Última 1s
        self.requests_1m: Deque[float] = deque()  # Último 1min
        self.requests_1h: Deque[float] = deque()  # Última 1h
        
        # Estado de backoff
        self.backoff_until: float = 0.0  # Timestamp até quando está em backoff
        self.current_backoff: float = 0.0  # Backoff atual em segundos
        
        # Lock para thread-safety
        self.lock = Lock()
        
        # Estatísticas
        self.total_requests = 0
        self.total_429_errors = 0
        self.total_wait_time = 0.0
    
    def _clean_old_requests(self, now: float) -> None:
        """Remove requisições antigas das janelas."""
        # Limpar janela de 1s
        while self.requests_1s and now - self.requests_1s[0] > 1.0:
            self.requests_1s.popleft()
        
        # Limpar janela de 1min
        while self.requests_1m and now - self.requests_1m[0] > 60.0:
            self.requests_1m.popleft()
        
        # Limpar janela de 1h
        while self.requests_1h and now - self.requests_1h[0] > 3600.0:
            self.requests_1h.popleft()
    
    def _calculate_wait_time(self, now: float) -> float:
        """Calcula tempo de espera necessário.
        
        Args:
            now: Timestamp atual
        
        Returns:
            Segundos a esperar antes da próxima requisição
        """
        wait_times = []
        
        # Check 1s window
        if len(self.requests_1s) >= self.config.max_requests_per_second:
            oldest = self.requests_1s[0]
            wait = 1.0 - (now - oldest)
            if wait > 0:
                wait_times.append(wait)
        
        # Check 1min window
        if len(self.requests_1m) >= self.config.max_requests_per_minute:
            oldest = self.requests_1m[0]
            wait = 60.0 - (now - oldest)
            if wait > 0:
                wait_times.append(wait)
        
        # Check 1h window
        if len(self.requests_1h) >= self.config.max_requests_per_hour:
            oldest = self.requests_1h[0]
            wait = 3600.0 - (now - oldest)
            if wait > 0:
                wait_times.append(wait)
        
        # Check backoff
        if now < self.backoff_until:
            wait_times.append(self.backoff_until - now)
        
        return max(wait_times) if wait_times else 0.0
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """Adquire permissão para fazer requisição.
        
        Bloqueia até que seja seguro fazer a requisição ou timeout expire.
        
        Args:
            timeout: Máximo de segundos a esperar (None = infinito)
        
        Returns:
            True se adquiriu, False se timeout
        """
        start_time = time.time()
        
        with self.lock:
            while True:
                now = time.time()
                
                # Limpar requisições antigas
                self._clean_old_requests(now)
                
                # Calcular tempo de espera
                wait = self._calculate_wait_time(now)
                
                if wait <= 0:
                    # Pode fazer requisição agora
                    self.requests_1s.append(now)
                    self.requests_1m.append(now)
                    self.requests_1h.append(now)
                    self.total_requests += 1
                    return True
                
                # Check timeout
                if timeout is not None:
                    elapsed = now - start_time
                    if elapsed + wait > timeout:
                        return False  # Timeout
                
                # Registrar tempo de espera
                self.total_wait_time += wait
        
        # Esperar fora do lock
        time.sleep(wait)
    
    def report_429(self) -> None:
        """Reporta que recebeu erro 429 (Too Many Requests).
        
        Ativa backoff exponencial.
        """
        with self.lock:
            self.total_429_errors += 1
            
            # Calcular novo backoff
            if self.current_backoff == 0:
                self.current_backoff = self.config.backoff_on_429
            else:
                self.current_backoff = min(
                    self.current_backoff * self.config.backoff_multiplier,
                    self.config.max_backoff
                )
            
            # Definir quando sair do backoff
            self.backoff_until = time.time() + self.current_backoff
            
            print(f"⚠️  Rate limit 429! Backoff por {self.current_backoff:.0f}s")
    
    def report_success(self) -> None:
        """Reporta que requisição foi bem-sucedida.
        
        Reseta backoff gradualmente.
        """
        with self.lock:
            # Se estava em backoff, reduzir
            if self.current_backoff > 0:
                self.current_backoff = max(
                    0,
                    self.current_backoff / self.config.backoff_multiplier
                )
    
    def get_stats(self) -> dict:
        """Retorna estatísticas de uso."""
        with self.lock:
            now = time.time()
            self._clean_old_requests(now)
            
            return {
                "total_requests": self.total_requests,
                "total_429s": self.total_429_errors,
                "total_429_errors": self.total_429_errors,  # Alias para compatibilidade
                "total_wait_time_seconds": self.total_wait_time,
                "requests_last_second": len(self.requests_1s),
                "requests_last_minute": len(self.requests_1m),
                "requests_last_hour": len(self.requests_1h),
                "window_1s": len(self.requests_1s),  # Alias
                "window_1m": len(self.requests_1m),  # Alias
                "window_1h": len(self.requests_1h),  # Alias
                "in_backoff": now < self.backoff_until,
                "backoff_seconds": self.current_backoff,
                "current_backoff_seconds": self.current_backoff,  # Alias para compatibilidade
                "config": asdict(self.config),
            }
    
    def save_stats(self, filename: str = ".rate_limit_stats.json") -> None:
        """Salva estatísticas em arquivo JSON."""
        stats = self.get_stats()
        stats["timestamp"] = datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
        
        try:
            Path(filename).write_text(json.dumps(stats, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"⚠️  Erro ao salvar stats de rate limit: {e}")


# Rate limiter global (singleton)
_global_limiter: Optional[RateLimiter] = None


def get_rate_limiter(config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """Obtém ou cria rate limiter global."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter(config)
    return _global_limiter


def reset_rate_limiter() -> None:
    """Reseta rate limiter global (útil para testes)."""
    global _global_limiter
    _global_limiter = None
