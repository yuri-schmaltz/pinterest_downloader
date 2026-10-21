#!/usr/bin/env python3
"""Sistema de ajuste dinâmico de workers baseado em performance.

Monitora CPU, RAM, latência de rede e ajusta o paralelismo automaticamente.
ONDA 5C - Adaptive Workers
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import psutil


@dataclass
class WorkerMetrics:
    """Métrica de performance de um worker."""

    timestamp: str
    cpu_percent: float  # % de CPU disponível
    memory_percent: float  # % de memória disponível
    active_workers: int  # Workers em uso
    success_rate: float  # Taxa de sucesso (0-1)
    avg_latency_ms: float  # Latência média de requisição


class AdaptiveWorkerManager:
    """Gerencia ajuste dinâmico de workers."""

    def __init__(
        self,
        min_workers: int = 4,
        max_workers: int = 32,
        target_cpu_percent: float = 70.0,
        target_memory_percent: float = 60.0,
        metrics_file: str = ".worker_metrics.json",
    ):
        """Inicializa gerenciador.

        Args:
            min_workers: Mínimo de workers (default: 4)
            max_workers: Máximo de workers (default: 32)
            target_cpu_percent: CPU alvo para ajuste (default: 70%)
            target_memory_percent: Memória alva (default: 60%)
            metrics_file: Arquivo para salvar métricas
        """
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.target_cpu = target_cpu_percent
        self.target_memory = target_memory_percent
        self.metrics_file = Path(metrics_file)

        self.current_workers = min_workers
        self.metrics_history: List[WorkerMetrics] = []
        self.success_count = 0
        self.total_count = 0
        self.latencies: List[float] = []

        # Carregar métricas anteriores
        self._load_metrics()

    def _get_timestamp(self) -> str:
        """Retorna timestamp ISO 8601."""
        return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"

    def _load_metrics(self) -> None:
        """Carrega histórico de métricas se existir."""
        if not self.metrics_file.exists():
            return

        try:
            with open(self.metrics_file, "r") as f:
                data = json.load(f)

            # Restaurar histórico (manter últimas 100 amostras)
            if isinstance(data, dict) and "metrics" in data:
                for m_dict in data["metrics"][-100:]:
                    # Recriar dataclass (json load retorna dict)
                    self.metrics_history.append(
                        WorkerMetrics(
                            timestamp=m_dict["timestamp"],
                            cpu_percent=m_dict["cpu_percent"],
                            memory_percent=m_dict["memory_percent"],
                            active_workers=m_dict["active_workers"],
                            success_rate=m_dict["success_rate"],
                            avg_latency_ms=m_dict["avg_latency_ms"],
                        )
                    )
        except Exception:
            pass  # Se falhar, começar do zero

    def record_success(self, latency_ms: float) -> None:
        """Registra uma requisição bem-sucedida.

        Args:
            latency_ms: Latência em milissegundos
        """
        self.success_count += 1
        self.total_count += 1
        self.latencies.append(latency_ms)

        # Manter apenas últimas 100 latências
        if len(self.latencies) > 100:
            self.latencies.pop(0)

    def record_failure(self) -> None:
        """Registra uma requisição falhada."""
        self.total_count += 1

    def get_success_rate(self) -> float:
        """Retorna taxa de sucesso (0-1)."""
        if self.total_count == 0:
            return 1.0
        return self.success_count / self.total_count

    def get_avg_latency(self) -> float:
        """Retorna latência média em ms."""
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    def get_system_metrics(self) -> tuple[float, float]:
        """Retorna CPU% e Memory% do sistema.

        Returns:
            (cpu_percent, memory_percent)
        """
        try:
            cpu = psutil.cpu_percent(interval=0.1)
        except Exception:
            cpu = 50.0  # Default se falhar

        try:
            memory = psutil.virtual_memory().percent
        except Exception:
            memory = 50.0  # Default se falhar

        return cpu, memory

    def _should_increase_workers(
        self,
        cpu: float,
        memory: float,
        success_rate: float,
        latency: float,
    ) -> bool:
        """Decide se deve aumentar workers.

        Args:
            cpu: CPU% atual
            memory: Memory% atual
            success_rate: Taxa de sucesso
            latency: Latência média

        Returns:
            True se deve aumentar
        """
        # Se CPU e memória estão confortáveis E sucesso é alto
        if cpu < self.target_cpu * 0.7 and memory < self.target_memory * 0.8:
            if success_rate > 0.95:
                return True

        return False

    def _should_decrease_workers(
        self,
        cpu: float,
        memory: float,
        success_rate: float,
    ) -> bool:
        """Decide se deve diminuir workers.

        Args:
            cpu: CPU% atual
            memory: Memory% atual
            success_rate: Taxa de sucesso

        Returns:
            True se deve diminuir
        """
        # Se CPU ou memória estão altas
        if cpu > self.target_cpu or memory > self.target_memory:
            return True

        # Se taxa de sucesso caiu muito
        if success_rate < 0.80:
            return True

        return False

    def adjust_workers(self) -> int:
        """Ajusta número de workers baseado em métricas.

        Returns:
            Novo número de workers recomendado
        """
        cpu, memory = self.get_system_metrics()
        success_rate = self.get_success_rate()
        avg_latency = self.get_avg_latency()

        # Registrar métrica
        metric = WorkerMetrics(
            timestamp=self._get_timestamp(),
            cpu_percent=cpu,
            memory_percent=memory,
            active_workers=self.current_workers,
            success_rate=success_rate,
            avg_latency_ms=avg_latency,
        )
        self.metrics_history.append(metric)

        # Manter apenas últimas 1000 métricas
        if len(self.metrics_history) > 1000:
            self.metrics_history = self.metrics_history[-1000:]

        # Lógica de ajuste
        if self._should_increase_workers(cpu, memory, success_rate, avg_latency):
            new_workers = min(self.current_workers + 1, self.max_workers)
            if new_workers != self.current_workers:
                self.current_workers = new_workers

        elif self._should_decrease_workers(cpu, memory, success_rate):
            new_workers = max(self.current_workers - 1, self.min_workers)
            if new_workers != self.current_workers:
                self.current_workers = new_workers

        return self.current_workers

    def save_metrics(self) -> None:
        """Salva histórico de métricas em JSON."""
        data = {
            "version": "1.0",
            "generated_at": self._get_timestamp(),
            "total_samples": len(self.metrics_history),
            "current_workers": self.current_workers,
            "success_rate": self.get_success_rate(),
            "avg_latency_ms": self.get_avg_latency(),
            "metrics": [asdict(m) for m in self.metrics_history],
        }

        try:
            self.metrics_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"⚠️  Erro ao salvar métricas: {e}")

    def get_summary(self) -> Dict:
        """Retorna resumo de performance."""
        return {
            "current_workers": self.current_workers,
            "min_workers": self.min_workers,
            "max_workers": self.max_workers,
            "success_rate": self.get_success_rate(),
            "avg_latency_ms": self.get_avg_latency(),
            "total_operations": self.total_count,
            "successful_operations": self.success_count,
            "cpu_target": self.target_cpu,
            "memory_target": self.target_memory,
            "metrics_samples": len(self.metrics_history),
        }


# Manager global (singleton)
_global_manager: Optional[AdaptiveWorkerManager] = None


def get_adaptive_manager(
    min_workers: int = 4,
    max_workers: int = 32,
) -> AdaptiveWorkerManager:
    """Obtém ou cria manager global."""
    global _global_manager
    if _global_manager is None:
        _global_manager = AdaptiveWorkerManager(
            min_workers=min_workers,
            max_workers=max_workers,
        )
    return _global_manager


def reset_adaptive_manager() -> None:
    """Reseta manager global (útil para testes)."""
    global _global_manager
    _global_manager = None
