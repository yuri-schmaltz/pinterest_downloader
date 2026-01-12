#!/usr/bin/env python3
"""Sistema de logging estruturado em JSON para Pinterest Board Downloader.

Rastreia cada fase (collect, resolve, download) com timestamps e métricas.
"""

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class LogEntry:
    """Entrada de log estruturada."""
    timestamp: str  # ISO 8601
    phase: str  # "collect_pins", "resolve_images", "download_images", etc
    level: str  # "INFO", "WARN", "ERROR"
    message: str
    duration_ms: Optional[float] = None  # Para operações com duração
    board_url: Optional[str] = None
    count: Optional[int] = None  # Pins coletados, imagens resolvidas, etc
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class JSONLogger:
    """Logger estruturado que escreve em JSON."""
    
    def __init__(self, output_file: str = "download_log.json", enabled: bool = True):
        """Inicializa logger.
        
        Args:
            output_file: Caminho do arquivo de log JSON
            enabled: Se logging deve estar ativado
        """
        self.output_file = Path(output_file)
        self.enabled = enabled
        self.entries: List[LogEntry] = []
        self.phase_start_time: Dict[str, float] = {}
    
    def _get_timestamp(self) -> str:
        """Retorna timestamp ISO 8601."""
        return datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
    
    def _log(self, entry: LogEntry) -> None:
        """Registra entry."""
        if not self.enabled:
            return
        
        self.entries.append(entry)
        
        # Também imprimir se for erro ou warning
        if entry.level in ("WARN", "ERROR"):
            symbol = "⚠️ " if entry.level == "WARN" else "❌ "
            print(f"{symbol}[{entry.phase}] {entry.message}", file=sys.stderr)
    
    def start_phase(self, phase: str) -> None:
        """Marca início de uma fase."""
        self.phase_start_time[phase] = time.time()
    
    def end_phase(self, phase: str, count: Optional[int] = None, message: str = "") -> None:
        """Marca fim de uma fase e registra duração."""
        if phase not in self.phase_start_time:
            return
        
        duration_ms = (time.time() - self.phase_start_time[phase]) * 1000
        
        entry = LogEntry(
            timestamp=self._get_timestamp(),
            phase=phase,
            level="INFO",
            message=message or f"{phase} completo",
            duration_ms=duration_ms,
            count=count,
        )
        self._log(entry)
        del self.phase_start_time[phase]
    
    def info(
        self,
        phase: str,
        message: str,
        board_url: Optional[str] = None,
        count: Optional[int] = None,
        **metadata,
    ) -> None:
        """Registra log INFO."""
        entry = LogEntry(
            timestamp=self._get_timestamp(),
            phase=phase,
            level="INFO",
            message=message,
            board_url=board_url,
            count=count,
            metadata=metadata,
        )
        self._log(entry)
    
    def warn(
        self,
        phase: str,
        message: str,
        board_url: Optional[str] = None,
        **metadata,
    ) -> None:
        """Registra log WARN."""
        entry = LogEntry(
            timestamp=self._get_timestamp(),
            phase=phase,
            level="WARN",
            message=message,
            board_url=board_url,
            metadata=metadata,
        )
        self._log(entry)
    
    def error(
        self,
        phase: str,
        message: str,
        error: Optional[str] = None,
        board_url: Optional[str] = None,
        **metadata,
    ) -> None:
        """Registra log ERROR."""
        entry = LogEntry(
            timestamp=self._get_timestamp(),
            phase=phase,
            level="ERROR",
            message=message,
            error=error,
            board_url=board_url,
            metadata=metadata,
        )
        self._log(entry)
    
    def save(self) -> None:
        """Salva logs em arquivo JSON."""
        if not self.enabled:
            return
        
        # Converter entries para dicts, removendo None values
        data = {
            "version": "1.0",
            "generated_at": self._get_timestamp(),
            "total_entries": len(self.entries),
            "logs": [
                {k: v for k, v in asdict(entry).items() if v is not None}
                for entry in self.entries
            ],
        }
        
        try:
            self.output_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"⚠️  Erro ao salvar logs: {e}", file=sys.stderr)
    
    def get_phase_duration(self, phase: str) -> Optional[float]:
        """Retorna duração total de uma fase em ms."""
        total = 0.0
        count = 0
        for entry in self.entries:
            if entry.phase == phase and entry.duration_ms:
                total += entry.duration_ms
                count += 1
        
        return total if count > 0 else None
    
    def get_summary(self) -> Dict[str, Any]:
        """Retorna resumo dos logs."""
        phases = {}
        for entry in self.entries:
            if entry.phase not in phases:
                phases[entry.phase] = {
                    "count": 0,
                    "duration_ms": 0.0,
                    "errors": 0,
                }
            
            phases[entry.phase]["count"] += 1
            if entry.duration_ms:
                phases[entry.phase]["duration_ms"] += entry.duration_ms
            if entry.level == "ERROR":
                phases[entry.phase]["errors"] += 1
        
        return {
            "total_entries": len(self.entries),
            "phases": phases,
        }


# Logger global (singleton)
_global_logger: Optional[JSONLogger] = None


def get_logger(output_file: str = "download_log.json", enabled: bool = True) -> JSONLogger:
    """Obtém ou cria logger global."""
    global _global_logger
    if _global_logger is None:
        _global_logger = JSONLogger(output_file, enabled)
    return _global_logger


def reset_logger() -> None:
    """Reseta logger global (útil para testes)."""
    global _global_logger
    _global_logger = None
