"""
Open-PY — Doctor (Diagnóstico e Auto-Reparo)
Sistema de auto-diagnóstico com 14 checks e reparo automático.
"""

import os
import shutil
import asyncio
from pathlib import Path
from dataclasses import dataclass, field

import psutil
import asyncpg

from shared.config import load_config
from shared.logger import get_logger

log = get_logger("doctor")


@dataclass
class CheckResult:
    ok: bool
    message: str = ""
    auto_fixable: bool = False


@dataclass
class DiagnosticReport:
    checks: dict = field(default_factory=dict)
    total: int = 0
    passed: int = 0
    failed: int = 0
    fixed: int = 0

    def add(self, name: str, result: CheckResult):
        self.checks[name] = result
        self.total += 1
        if result.ok:
            self.passed += 1
        else:
            self.failed += 1

    def summary(self) -> str:
        emoji = "✅" if self.failed == 0 else "⚠️"
        text = f"{emoji} Diagnóstico: {self.passed}/{self.total} checks OK"
        if self.fixed > 0:
            text += f" ({self.fixed} corrigidos)"
        text += "\n\n"
        for name, result in self.checks.items():
            icon = "✅" if result.ok else "❌"
            text += f"{icon} {name}: {result.message}\n"
        return text


class Doctor:
    """Sistema de auto-diagnóstico e reparo"""

    def __init__(self, install_dir: str = "/opt/open-py"):
        self.install_dir = Path(install_dir)

    async def run_full_diagnostic(self, auto_repair: bool = True) -> DiagnosticReport:
        """Executa diagnóstico completo"""
        report = DiagnosticReport()
        config = load_config()

        # 1. Config exists
        config_path = self.install_dir / "openpy.toml"
        report.add("config_exists", CheckResult(
            ok=config_path.exists(),
            message="OK" if config_path.exists() else "openpy.toml não encontrado",
            auto_fixable=False,
        ))

        # 2. Diretórios necessários
        required_dirs = [
            "data/agents", "data/memory/daily", "data/media/photo",
            "data/media/audio", "data/media/video", "data/media/document",
            "data/tools/custom", "data/backups",
        ]
        missing_dirs = []
        for d in required_dirs:
            full = self.install_dir / d
            if not full.exists():
                missing_dirs.append(d)
        report.add("directories", CheckResult(
            ok=len(missing_dirs) == 0,
            message="OK" if not missing_dirs else f"Faltando: {', '.join(missing_dirs)}",
            auto_fixable=True,
        ))

        # 3. Database
        try:
            conn = await asyncpg.connect(config.database.dsn)
            await conn.fetchval("SELECT 1")
            await conn.close()
            report.add("database", CheckResult(ok=True, message="PostgreSQL acessível"))
        except Exception as e:
            report.add("database", CheckResult(
                ok=False, message=f"PostgreSQL inacessível: {e}", auto_fixable=False,
            ))

        # 4. DB Tables
        try:
            conn = await asyncpg.connect(config.database.dsn)
            tables = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
            await conn.close()
            existing = {r['tablename'] for r in tables}
            required = {'memories', 'daily_compilations', 'tasks', 'agent_logs', 'agent_configs'}
            missing = required - existing
            report.add("db_tables", CheckResult(
                ok=len(missing) == 0,
                message="OK" if not missing else f"Faltando: {', '.join(missing)}",
                auto_fixable=True,
            ))
        except Exception:
            report.add("db_tables", CheckResult(ok=False, message="Não foi possível verificar"))

        # 5. DB Extensions
        try:
            conn = await asyncpg.connect(config.database.dsn)
            exts = await conn.fetch("SELECT extname FROM pg_extension")
            await conn.close()
            ext_names = {r['extname'] for r in exts}
            has_vector = 'vector' in ext_names
            has_trgm = 'pg_trgm' in ext_names
            report.add("db_extensions", CheckResult(
                ok=has_vector and has_trgm,
                message="OK" if (has_vector and has_trgm) else f"Faltando: {'vector' if not has_vector else ''} {'pg_trgm' if not has_trgm else ''}",
                auto_fixable=True,
            ))
        except Exception:
            report.add("db_extensions", CheckResult(ok=False, message="Não verificado"))

        # 6. Python venv
        venv_python = self.install_dir / "venv" / "bin" / "python3"
        report.add("venv", CheckResult(
            ok=venv_python.exists(),
            message="OK" if venv_python.exists() else "venv não encontrado",
            auto_fixable=False,
        ))

        # 7. Bubblewrap
        bwrap = shutil.which("bwrap")
        report.add("bwrap", CheckResult(
            ok=bwrap is not None,
            message="OK" if bwrap else "bwrap não instalado",
            auto_fixable=False,
        ))

        # 8. FFmpeg
        ffmpeg = shutil.which("ffmpeg")
        report.add("ffmpeg", CheckResult(
            ok=ffmpeg is not None,
            message="OK" if ffmpeg else "ffmpeg não instalado",
            auto_fixable=False,
        ))

        # 9. soul.md
        soul = self.install_dir / "data" / "soul.md"
        report.add("soul_md", CheckResult(
            ok=soul.exists(),
            message="OK" if soul.exists() else "soul.md não encontrado",
            auto_fixable=False,
        ))

        # 10. essence.md
        essence = self.install_dir / "data" / "essence.md"
        report.add("essence_md", CheckResult(
            ok=essence.exists(),
            message="OK" if essence.exists() else "essence.md não encontrado",
            auto_fixable=False,
        ))

        # 11. Disk space
        disk = psutil.disk_usage("/")
        free_mb = disk.free // (1024 * 1024)
        report.add("disk_space", CheckResult(
            ok=free_mb > 100,
            message=f"{free_mb}MB livres" if free_mb > 100 else f"CRÍTICO: apenas {free_mb}MB",
        ))

        # 12. RAM
        mem = psutil.virtual_memory()
        report.add("ram", CheckResult(
            ok=mem.percent < 90,
            message=f"{mem.percent}% usado",
        ))

        # 13. Telegram token
        has_token = bool(config.telegram.bot_token)
        report.add("telegram_token", CheckResult(
            ok=has_token,
            message="OK" if has_token else "Token não configurado",
        ))

        # 14. Socket dir
        socket_dir = Path("/tmp/open-py/agents")
        report.add("socket_dir", CheckResult(
            ok=socket_dir.exists(),
            message="OK" if socket_dir.exists() else "Diretório de sockets não existe",
            auto_fixable=True,
        ))

        # AUTO-REPARO
        if auto_repair:
            report.fixed = await self._auto_repair(report)

        return report

    async def _auto_repair(self, report: DiagnosticReport) -> int:
        """Tenta reparar problemas automaticamente"""
        fixed = 0

        # Diretórios
        if not report.checks.get("directories", CheckResult(ok=True)).ok:
            for d in ["data/agents", "data/memory/daily", "data/media/photo",
                       "data/media/audio", "data/media/video", "data/media/document",
                       "data/tools/custom", "data/backups"]:
                (self.install_dir / d).mkdir(parents=True, exist_ok=True)
            fixed += 1
            log.info("🔧 Diretórios criados")

        # Socket dir
        if not report.checks.get("socket_dir", CheckResult(ok=True)).ok:
            Path("/tmp/open-py/agents").mkdir(parents=True, exist_ok=True)
            fixed += 1
            log.info("🔧 Socket dir criado")

        # DB tables
        if not report.checks.get("db_tables", CheckResult(ok=True)).ok:
            try:
                config = load_config()
                from shared.migrations import run_migrations
                await run_migrations(config.database.dsn)
                fixed += 1
                log.info("🔧 Tabelas do banco recriadas")
            except Exception:
                pass

        return fixed
