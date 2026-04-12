"""
Open-PY v5.1 — Scheduler Manager
Heartbeat, proatividade, goals, cleanup, Ollama recovery, self-review.

v5.1: 5 novos jobs para autonomia real:
- Ollama health check (recovery automático)
- Skill cleanup (remove skills obsoletas)
- Core memory persistence (salva a cada 15min)
- Self-review (auto-avaliação diária)
- Goal pulse (persegue objetivos ativos)
- Proactive notifications (alertas no Telegram)
"""

import json
import psutil
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.logger import get_logger

log = get_logger("scheduler")


class SchedulerManager:
    """Gerenciador de tarefas agendadas v5.1 — proatividade real."""

    def __init__(self, core):
        self.core = core
        self.scheduler = AsyncIOScheduler()
        self._last_heartbeat: str = "never"
        self._proactive_queue: list[str] = []  # Mensagens para enviar ao user

    async def start(self):
        """Inicia o scheduler com todos os jobs (base + v5.1)."""
        config = self.core.config

        # === JOBS BASE ===

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

        # === JOBS v5.1: PROATIVIDADE ===

        # Ollama health check — a cada 2 min
        self.scheduler.add_job(
            self._ollama_health,
            'interval',
            minutes=2,
            id="ollama_health",
        )

        # Core memory persistence — a cada 15 min
        self.scheduler.add_job(
            self._core_memory_persist,
            'interval',
            minutes=15,
            id="core_memory_persist",
        )

        # Skill cleanup — 1x/dia às 03:00
        self.scheduler.add_job(
            self._skill_cleanup,
            'cron',
            hour=3, minute=0,
            id="skill_cleanup",
        )

        # Self-review — 1x/dia às 04:00
        self.scheduler.add_job(
            self._self_review,
            'cron',
            hour=4, minute=0,
            id="self_review",
        )

        # Goal pulse — a cada 10 min
        self.scheduler.add_job(
            self._goal_pulse,
            'interval',
            minutes=10,
            id="goal_pulse",
        )

        # Reset daily goal actions — 1x/dia à meia-noite
        self.scheduler.add_job(
            self._reset_daily_goal_actions,
            'cron',
            hour=0, minute=1,
            id="reset_goal_actions",
        )

        self.scheduler.start()
        log.info("✅ Scheduler v5.1 iniciado",
                 heartbeat=f"{interval}s",
                 migration=f"{config.memory.migration_hour:02d}:{config.memory.migration_minute:02d}",
                 jobs=len(self.scheduler.get_jobs()))

    def shutdown(self):
        """Para o scheduler."""
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    # ============================================
    # HEARTBEAT + PROACTIVE ALERTS
    # ============================================

    async def _heartbeat(self):
        """Health check periódico com alertas proativos."""
        report = {"timestamp": datetime.now().isoformat(), "checks": {}}

        # RAM
        mem = psutil.virtual_memory()
        report["checks"]["ram"] = {
            "ok": mem.percent < 90,
            "value": f"{mem.percent}%",
        }
        if mem.percent >= 90:
            await self._notify(f"⚠️ RAM em {mem.percent}% — risco de OOM!")

        # Disco
        disk = psutil.disk_usage("/")
        report["checks"]["disk"] = {
            "ok": disk.percent < 95,
            "value": f"{disk.percent}%",
        }
        if disk.percent >= 95:
            await self._notify(f"🚨 Disco em {disk.percent}% — quase cheio!")

        # DB
        db_ok = self.core.db_pool is not None
        report["checks"]["database"] = {"ok": db_ok}

        # LLM
        llm_ok = self.core.llm_router is not None and self.core.llm_router._available
        report["checks"]["llm"] = {"ok": llm_ok}
        if not llm_ok:
            await self._notify("🔴 LLM indisponível — não consigo processar mensagens!")

        # Status geral
        failed = [k for k, v in report["checks"].items() if not v["ok"]]
        if failed:
            log.warning("💓 Heartbeat: DEGRADED", failed=failed)
        else:
            log.debug("💓 Heartbeat: OK")

        self._last_heartbeat = report["timestamp"]

    # ============================================
    # v5.1: PROACTIVE NOTIFICATION
    # ============================================

    async def _notify(self, message: str):
        """Envia notificação proativa no Telegram."""
        bot = self.core.telegram_bot
        if not bot or not hasattr(bot, '_bot'):
            log.info("📢 Notificação (sem Telegram):", msg=message)
            return

        try:
            # Pegar user_id do config
            allowed_users = self.core.config.telegram.allowed_users
            if not allowed_users:
                return

            for user_id in allowed_users:
                if user_id and user_id != 0:
                    await bot._bot.send_message(
                        chat_id=user_id,
                        text=f"🤖 *Open-PY*\n\n{message}",
                        parse_mode="Markdown",
                    )
            log.info("📢 Notificação proativa enviada", msg=message[:80])
        except Exception as e:
            log.warning("⚠️ Falha ao enviar notificação", error=str(e))

    # ============================================
    # v5.1: OLLAMA HEALTH CHECK
    # ============================================

    async def _ollama_health(self):
        """Verifica se Ollama está vivo e reseta backoff se voltou."""
        if not self.core.memory_manager:
            return
        try:
            recovered = await self.core.memory_manager.ollama_health_check()
            if recovered:
                log.debug("🦙 Ollama health: OK")
        except Exception as e:
            log.debug("🦙 Ollama health check falhou", error=str(e))

    # ============================================
    # v5.1: CORE MEMORY PERSISTENCE
    # ============================================

    async def _core_memory_persist(self):
        """Salva core memory no PostgreSQL a cada 15min."""
        if not self.core.memory_manager:
            return
        try:
            await self.core.memory_manager.save_core_memory()
        except Exception as e:
            log.error("⚠️ Erro persistindo core memory", error=str(e))

    # ============================================
    # v5.1: SKILL CLEANUP
    # ============================================

    async def _skill_cleanup(self):
        """Remove skills obsoletas (0 sucessos após 7 dias)."""
        if not self.core.db_pool:
            return
        try:
            result = await self.core.db_pool.execute("""
                DELETE FROM skills
                WHERE success_count = 0
                  AND failure_count > 0
                  AND last_used < NOW() - INTERVAL '7 days'
            """)
            deleted = int(result.split()[-1]) if result else 0
            if deleted > 0:
                log.info("🗑️ Skills obsoletas removidas", count=deleted)
                await self._notify(f"🧹 Limpeza: {deleted} skills obsoletas removidas")

            # Também limpar skills muito antigas sem uso
            result2 = await self.core.db_pool.execute("""
                DELETE FROM skills
                WHERE last_used < NOW() - INTERVAL '90 days'
                  AND success_count < 3
            """)
            old_deleted = int(result2.split()[-1]) if result2 else 0
            if old_deleted > 0:
                log.info("🗑️ Skills antigas removidas", count=old_deleted)

        except Exception as e:
            log.error("❌ Erro no skill cleanup", error=str(e))

    # ============================================
    # v5.1: SELF-REVIEW (AUTO-AVALIAÇÃO)
    # ============================================

    async def _self_review(self):
        """Auto-avaliação diária — o agente reflete sobre seu desempenho."""
        if not self.core.cortex or not self.core.llm_router:
            return

        try:
            stats = self.core.cortex.get_metrics()

            # Stats de skills
            skill_count = 0
            if self.core.db_pool:
                skill_count = await self.core.db_pool.fetchval(
                    "SELECT COUNT(*) FROM skills"
                ) or 0

            # Stats de goals
            goal_count = 0
            if self.core.db_pool:
                goal_count = await self.core.db_pool.fetchval(
                    "SELECT COUNT(*) FROM goals WHERE status = 'active'"
                ) or 0

            prompt = f"""Reflita sobre seu desempenho das últimas 24h:
- Total requests processados: {stats['total_requests']}
- Distribuição de profundidade: {stats['depth_distribution']}
- Tokens estimados: {stats['total_tokens_estimated']}
- Skills aprendidas: {skill_count}
- Goals ativos: {goal_count}

Baseado nesses dados:
1. Identifique padrões (que tipos de requests são mais comuns?)
2. Sugira 1-2 melhorias CONCRETAS
3. Se necessário, atualize sua core memory com insights relevantes usando core_memory_update no bloco 'directives'"""

            response = await self.core.llm_router.complete(
                [{"role": "system", "content": "Você é o Open-PY refletindo sobre seu próprio desempenho. Seja conciso e prático."},
                 {"role": "user", "content": prompt}],
                max_tokens=500,
                thinking=False,
            )
            log.info("🪞 Self-review concluído", preview=str(response)[:100])

        except Exception as e:
            log.error("❌ Self-review falhou", error=str(e))

    # ============================================
    # v5.1: GOAL PULSE (PERSEGUE OBJETIVOS)
    # ============================================

    async def _goal_pulse(self):
        """Verifica goals ativos e executa próximo passo se possível."""
        if not self.core.db_pool or not self.core.cortex:
            return

        try:
            # Buscar goals ativos com ações restantes hoje, ordenados por prioridade
            goals = await self.core.db_pool.fetch("""
                SELECT id, title, description, next_step, actions_today,
                       max_daily_actions, progress_pct
                FROM goals
                WHERE status = 'active'
                  AND actions_today < max_daily_actions
                ORDER BY priority DESC
                LIMIT 1
            """)

            if not goals:
                return

            goal = goals[0]
            goal_id = goal["id"]
            next_step = goal["next_step"]

            if not next_step:
                return

            log.info("🎯 Goal pulse: executando próximo passo",
                     goal=goal["title"],
                     step=next_step[:60],
                     progress=f"{goal['progress_pct']}%")

            # Executar o próximo passo via Cortex
            result = await self.core.cortex.process(
                raw_input=f"[GOAL: {goal['title']}] {next_step}",
                input_type="automation",
                user_id=0,  # System-initiated
            )

            # Atualizar goal
            if result.success:
                new_progress = min(goal["progress_pct"] + 10, 100)
                status = "completed" if new_progress >= 100 else "active"

                await self.core.db_pool.execute("""
                    UPDATE goals SET
                        actions_today = actions_today + 1,
                        last_action = $1,
                        progress_pct = $2,
                        status = $3,
                        updated_at = NOW()
                    WHERE id = $4
                """, result.response[:500], new_progress, status, goal_id)

                if status == "completed":
                    await self._notify(f"🎉 Goal completo: *{goal['title']}*")
                    log.info("🎉 Goal completado!", goal=goal["title"])
            else:
                await self.core.db_pool.execute("""
                    UPDATE goals SET
                        actions_today = actions_today + 1,
                        last_action = $1,
                        updated_at = NOW()
                    WHERE id = $2
                """, f"FALHA: {result.error or 'erro desconhecido'}", goal_id)

        except Exception as e:
            log.error("❌ Goal pulse falhou", error=str(e))

    async def _reset_daily_goal_actions(self):
        """Reset do contador diário de ações dos goals à meia-noite."""
        if not self.core.db_pool:
            return
        try:
            await self.core.db_pool.execute("""
                UPDATE goals SET actions_today = 0
                WHERE status = 'active'
            """)
            log.info("🔄 Goal actions resetadas para o novo dia")
        except Exception as e:
            log.error("❌ Erro resetando goal actions", error=str(e))

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
        """Migra memory.md → PostgreSQL diariamente."""
        log.info("📦 Iniciando migração diária de memórias")
        if self.core.memory_manager:
            try:
                await self.core.memory_manager.migrate_daily()
                log.info("✅ Migração diária concluída")
            except Exception as e:
                log.error("❌ Erro na migração diária", error=str(e))

    async def _memory_flush(self):
        """Força salvamento do buffer de memória."""
        if self.core.memory_manager:
            try:
                await self.core.memory_manager.flush()
            except Exception as e:
                log.error("Erro no flush de memória", error=str(e))
