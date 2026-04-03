"""
Open-PY — Structured Logging
Usa structlog para logs JSON estruturados com Rich para terminal bonito.
"""

import sys
import logging
import structlog
from rich.console import Console

console = Console()


def setup_logging(level: str = "INFO", json_output: bool = False):
    """Configura o sistema de logging global"""

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(
            colors=True,
            pad_level=True,
        ))

    # logging.getLevelName retorna int para nomes válidos (INFO→20, CRITICAL→50)
    numeric_level = logging.getLevelName(level.upper())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = None) -> structlog.BoundLogger:
    """Retorna um logger estruturado"""
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log
