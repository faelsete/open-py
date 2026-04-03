"""
Open-PY — Orchestrator
Gerencia delegação de tarefas para agentes, monitora execução e coleta resultados.
"""

import asyncio
from datetime import datetime
from typing import Optional

from shared.models import (
    ThinkingResult, AgentTask, AgentResult, TaskStatus,
    IPCMessage, IPCResponse
)
from shared.logger import get_logger
from shared.exceptions import AgentNotFoundError, AgentTimeoutError

log = get_logger("orchestrator")


class Orchestrator:
    """
    Orquestra a delegação de tarefas para agentes.
    Fluxo: ThinkingResult → Encontrar/criar agente → Despachar → Monitorar → Coletar
    """

    def __init__(self, agent_registry=None, agent_factory=None,
                 memory_manager=None, db_pool=None):
        self.registry = agent_registry
        self.factory = agent_factory
        self.memory = memory_manager
        self.db = db_pool
        self._active_tasks: dict[str, AgentTask] = {}

    async def dispatch(self, thinking: ThinkingResult,
                       attachments: list[str] = None) -> AgentResult:
        """
        Despacha uma tarefa baseado no resultado do Thinking Engine.
        """
        if not thinking.target_agent:
            return AgentResult(
                task_id=thinking.task_id or "",
                status=TaskStatus.COMPLETED,
                output="[Core resolve diretamente]"
            )

        log.info("🔀 Despachando tarefa",
                 agent=thinking.target_agent,
                 task_id=thinking.task_id)

        # 1. Encontrar ou criar agente
        agent = self.registry.get(thinking.target_agent) if self.registry else None

        if not agent and self.factory:
            log.info("➕ Agente não encontrado, criando...", agent=thinking.target_agent)
            agent = await self.factory.create_builtin(thinking.target_agent)

        if not agent:
            raise AgentNotFoundError(
                f"Agente '{thinking.target_agent}' não encontrado e não pode ser criado"
            )

        # 2. Montar tarefa
        task = AgentTask(
            task_id=thinking.task_id or f"TASK-{datetime.now().strftime('%H%M%S')}",
            task=thinking.raw_input,
            context={
                "delegation_reason": thinking.delegation_reason,
                "urgency": thinking.urgency.value,
                "required_tools": thinking.required_tools,
            },
            attachments=attachments or [],
            timeout=thinking.urgency.timeout,
        )

        # 3. Registrar tarefa
        self._active_tasks[task.task_id] = task
        await self._save_task_to_db(task)

        # 4. Executar
        try:
            result = await asyncio.wait_for(
                agent.execute(task),
                timeout=task.timeout
            )
        except asyncio.TimeoutError:
            result = AgentResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=f"Timeout após {task.timeout}s"
            )
            log.error("⏰ Timeout na execução", task_id=task.task_id)
        except Exception as e:
            result = AgentResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(e)
            )
            log.error("❌ Erro na execução", task_id=task.task_id, error=str(e))

        # 5. Salvar memórias geradas pelo agente
        if result.memories and self.memory:
            for mem_text in result.memories:
                await self.memory.save_memory(
                    content=mem_text,
                    source=f"agent:{thinking.target_agent}",
                    tags=["auto", thinking.target_agent],
                )

        # 6. Atualizar status da tarefa
        await self._update_task_status(task.task_id, result.status, result.output)

        # 7. Cleanup
        del self._active_tasks[task.task_id]

        log.info("✅ Tarefa concluída",
                 task_id=task.task_id,
                 status=result.status.value)

        return result

    async def get_active_tasks(self) -> list[dict]:
        """Lista tarefas ativas"""
        return [
            {"task_id": t.task_id, "task": t.task[:100], "created_at": t.created_at.isoformat()}
            for t in self._active_tasks.values()
        ]

    async def cancel_task(self, task_id: str) -> bool:
        """Cancela uma tarefa ativa"""
        if task_id in self._active_tasks:
            del self._active_tasks[task_id]
            await self._update_task_status(task_id, TaskStatus.CANCELLED)
            return True
        return False

    # ============================================
    # BANCO DE DADOS
    # ============================================

    async def _save_task_to_db(self, task: AgentTask):
        """Persiste tarefa no banco"""
        if not self.db:
            return
        try:
            await self.db.execute("""
                INSERT INTO tasks (id, title, description, status, created_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET status = $4, updated_at = NOW()
            """, task.task_id, task.task[:200], task.task, "running",
                 task.created_at)
        except Exception as e:
            log.warning("DB save failed", error=str(e))

    async def _update_task_status(self, task_id: str,
                                   status: TaskStatus,
                                   result: str = None):
        """Atualiza status da tarefa no banco"""
        if not self.db:
            return
        try:
            await self.db.execute("""
                UPDATE tasks SET status = $2, result = $3, updated_at = NOW(),
                completed_at = CASE WHEN $2 IN ('completed','failed','cancelled')
                               THEN NOW() ELSE NULL END
                WHERE id = $1
            """, task_id, status.value, result)
        except Exception as e:
            log.warning("DB update failed", error=str(e))
