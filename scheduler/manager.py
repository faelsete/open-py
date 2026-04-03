"""
Open-PY — Scheduler Manager
Heartbeat, cron jobs e migração diária de memórias.
"""

import psutil
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.logger import get_logger

log = get_logger("scheduler")


class SchedulerManager:
    """Gerenciador de tarefas agendadas"""

    def __init__(self, core):
        self.core = core
        self.scheduler = AsyncIOScheduler()
        self._last_heartbeat: str = "never"

    async def start(self):
        """Inicia o scheduler com todos os jobs padrão"""
        config = self.core.config

        # Heartbeat — a cada N segundos
        interval = config.scheduler.heartbeat_interval_seconds
        self.scheduler.add_job(
            self._heartbeat,
            'interval',
            seconds=interval,
            id="heartbeat",
        )

        # Migração diária de memórias — horário configurável
        self.scheduler.add_job(
            self._daily_memory_migration,
            'cron',
            hour=config.memory.migration_hour,
            minute=config.memory.migration_minute,
            id="memory_migration",
        )

        # Flush de memória — a cada 1 hora (segurança)
        self.scheduler.add_job(
            self._memory_flush,
            'interval',
            minutes=config.memory.context_save_interval_minutes,
            id="memory_flush",
        )

        self.scheduler.start()
        log.info("✅ Scheduler iniciado",
                 heartbeat=f"{interval}s",
                 migration=f"{config.memory.migration_hour:02d}:{config.memory.migration_minute:02d}")

    def shutdown(self):
        """Para o scheduler"""
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    # ============================================
    # HEARTBEAT
    # ============================================

    async def _heartbeat(self):
        """Health check periódico"""
        report = {"timestamp": datetime.now().isoformat(), "checks": {}}

        # RAM
        mem = psutil.virtual_memory()
        report["checks"]["ram"] = {
            "ok": mem.percent < 90,
            "value": f"{mem.percent}%",
        }

        # Disco
        disk = psutil.disk_usage("/")
        report["checks"]["disk"] = {
            "ok": disk.percent < 95,
            "value": f"{disk.percent}%",
        }

        # DB
        db_ok = self.core.db_pool is not None
        report["checks"]["database"] = {"ok": db_ok}

        # LLM
        llm_ok = self.core.llm_router is not None and self.core.llm_router._available
        report["checks"]["llm"] = {"ok": llm_ok}

        # Status geral
        failed = [k for k, v in report["checks"].items() if not v["ok"]]
        if failed:
            log.warning("💓 Heartbeat: DEGRADED", failed=failed)
        else:
            log.debug("💓 Heartbeat: OK")

        self._last_heartbeat = report["timestamp"]

    # ============================================
    # MEMÓRIA
    # ============================================

    async def _daily_memory_migration(self):
        """Migra memory.md → PostgreSQL diariamente"""
        log.info("📦 Iniciando migração diária de memórias")
        if self.core.memory_manager:
            try:
                await self.core.memory_manager.migrate_daily()
                log.info("✅ Migração diária concluída")
            except Exception as e:
                log.error("❌ Erro na migração diária", error=str(e))

    async def _memory_flush(self):
        """Força salvamento do buffer de memória"""
        if self.core.memory_manager:
            try:
                await self.core.memory_manager.flush()
            except Exception as e:
                log.error("Erro no flush de memória", error=str(e))
