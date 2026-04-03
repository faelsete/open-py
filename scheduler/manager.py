"""
Open-PY — Scheduler Manager
Heartbeat, cron jobs, cleanup e migração diária de memórias.
"""

import psutil
from datetime import datetime, timedelta

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

        # Cleanup — a cada 5 min (evita vazamento de memória em bots de longo uptime)
        self.scheduler.add_job(
            self._cleanup,
            'interval',
            minutes=5,
            id="cleanup",
        )

        self.scheduler.start()
        log.info("✅ Scheduler iniciado",
                 heartbeat=f"{interval}s",
                 migration=f"{config.memory.migration_hour:02d}:{config.memory.migration_minute:02d}",
                 cleanup="5min")

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
    # CLEANUP — Evita memory leak em bots de longo uptime
    # ============================================

    async def _cleanup(self):
        """
        Limpeza periódica de estado stale (a cada 5 min):
        - Chats inativos > 10min no batcher/pending_replies
        - Entradas expiradas no rate limiter
        - Tasks órfãs no orchestrator
        """
        cleaned = 0
        now = datetime.now()
        cutoff = now - timedelta(minutes=10)

        # 1. Limpar pending_replies do Telegram bot (chats inativos > 10min)
        bot = self.core.telegram_bot
        if bot and hasattr(bot, '_pending_replies'):
            stale_chats = []
            for chat_id, msg in bot._pending_replies.items():
                if hasattr(msg, 'date') and msg.date:
                    try:
                        msg_time = msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date
                        if msg_time < cutoff:
                            stale_chats.append(chat_id)
                    except Exception:
                        stale_chats.append(chat_id)
            for chat_id in stale_chats:
                bot._pending_replies.pop(chat_id, None)
                cleaned += 1

        # 2. Limpar batcher (chats com timers cancelados/expirados)
        if bot and hasattr(bot, 'batcher') and hasattr(bot.batcher, '_pending'):
            stale_batch = [
                cid for cid in list(bot.batcher._pending.keys())
                if cid not in (bot._pending_replies or {})
            ]
            for cid in stale_batch:
                bot.batcher._pending.pop(cid, None)
                cleaned += 1

        # 3. Limpar rate limiter buckets velhos (> 30min sem uso)
        if bot and hasattr(bot, 'rate_limiter') and hasattr(bot.rate_limiter, '_buckets'):
            rl = bot.rate_limiter
            old_cutoff = now.timestamp() - 1800  # 30 min
            stale_buckets = [
                k for k, v in rl._buckets.items()
                if hasattr(v, 'last_update') and v.last_update < old_cutoff
            ]
            for k in stale_buckets:
                del rl._buckets[k]
                cleaned += 1

        # 4. Limpar tarefas órfãs no orchestrator (> 30min)
        if self.core.orchestrator and hasattr(self.core.orchestrator, '_active_tasks'):
            orch = self.core.orchestrator
            stale_tasks = [
                tid for tid, task in orch._active_tasks.items()
                if hasattr(task, 'created_at') and task.created_at < cutoff
            ]
            for tid in stale_tasks:
                orch._active_tasks.pop(tid, None)
                cleaned += 1

        if cleaned > 0:
            log.info("🧹 Cleanup: removidos itens stale", cleaned=cleaned)

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
