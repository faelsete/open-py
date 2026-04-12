"""
Open-PY — Orchestrator v2.0
Gerencia delegação de tarefas com:
- Fallback routing (agente offline → agent:general ou Core)
- Retry com backoff
- Quotas para agent_creator
- Context compression
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from shared.models import (
    ThinkingResult, AgentTask, AgentResult, TaskStatus,
    IPCMessage, IPCResponse
)
from shared.logger import get_logger
from shared.exceptions import AgentNotFoundError, AgentTimeoutError

log = get_logger("orchestrator")

# ============================================
# FALLBACK MAP — Quando agente alvo falha
# ============================================

FALLBACK_ROUTES = {
    "vision": ["builder", None],        # vision falha → tenta builder → Core
    "builder": [None],                    # builder falha → Core resolve
    "transcriber": ["builder", None],    # transcriber falha → builder → Core
    "researcher": ["builder", None],     # researcher falha → builder → Core
    "cleaner": [None],                    # cleaner falha → Core
    "agent_creator": [None],             # agent_creator falha → Core
}

# ============================================
# QUOTAS — Limites de criação de agentes
# ============================================

AGENT_CREATION_QUOTAS = {
    "max_agents_total": 20,          # Máximo de agentes ativos
    "max_agents_per_hour": 5,        # Máximo de criações por hora
    "max_custom_agents": 10,         # Máximo de agentes customizados
    "require_confirmation": True,    # Exigir confirmação do usuário
}


class Orchestrator:
    """
    Orquestra a delegação de tarefas para agentes.
    Fluxo: ThinkingResult → Encontrar/criar agente → Despachar → Monitorar → Coletar

    v2.0: Fallback routing, retry, quotas, context compression
    """

    def __init__(self, agent_registry=None, agent_factory=None,
                 memory_manager=None, db_pool=None, audit_log=None):
        self.registry = agent_registry
        self.factory = agent_factory
        self.memory = memory_manager
        self.db = db_pool
        self.audit = audit_log
        self._active_tasks: dict[str, AgentTask] = {}

        # Tracking para quotas
        self._creation_log: list[datetime] = []  # timestamps de criação
        self._custom_agent_count: int = 0

        # Healthcheck state
        self._agent_health: dict[str, dict] = defaultdict(
            lambda: {"failures": 0, "last_failure": None, "healthy": True}
        )

        # Fallback stats (observabilidade)
        self._fallback_stats: dict[str, int] = defaultdict(int)  # agent → fallback count

    async def dispatch(self, thinking: ThinkingResult,
                       attachments: list[str] = None,
                       conversation_history: list[dict] = None) -> AgentResult:
        """
        Despacha uma tarefa baseado no resultado do Thinking Engine.
        Inclui fallback routing, context injection e retry.
        """
        if not thinking.target_agent:
            return AgentResult(
                task_id=thinking.task_id or "",
                status=TaskStatus.COMPLETED,
                output="[Core resolve diretamente]"
            )

        log.info("🔀 Despachando tarefa",
                 agent=thinking.target_agent,
                 task_id=thinking.task_id,
                 history_msgs=len(conversation_history or []))

        # Montar tarefa com context compression + histórico
        task = self._build_task(thinking, attachments, conversation_history)

        # Tentar executar com fallback chain
        agents_to_try = [thinking.target_agent] + FALLBACK_ROUTES.get(
            thinking.target_agent, [None]
        )

        for agent_name in agents_to_try:
            if agent_name is None:
                # Fallback EXPLÍCITO: Core assume com log detalhado
                chain_tried = [a for a in agents_to_try if a is not None]
                log.warning(
                    "🔄 FALLBACK → Core assumindo tarefa",
                    original_agent=thinking.target_agent,
                    chain_tried=chain_tried,
                    reason="Nenhum agente na chain está disponível/saudável",
                    task_preview=task.task[:200],
                )
                self._fallback_stats[thinking.target_agent] += 1

                # Registrar no audit log
                if self.audit:
                    try:
                        await self.audit.log(
                            actor="system:orchestrator",
                            action="fallback_to_core",
                            target=thinking.target_agent,
                            severity="warning",
                            payload={
                                "chain_tried": chain_tried,
                                "task_id": task.task_id,
                                "reason": "agent_chain_exhausted",
                            }
                        )
                    except Exception:
                        pass

                return AgentResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    output=f"[Core resolvendo diretamente — agente '{thinking.target_agent}' indisponível (chain: {chain_tried})]"
                )

            # Checar se agente está saudável
            if not self._is_agent_healthy(agent_name):
                log.warning("⚠️ Agente marcado como não-saudável, pulando",
                           agent=agent_name)
                continue

            result = await self._try_execute(agent_name, task, thinking)
            if result.status != TaskStatus.FAILED:
                # Sucesso! Resetar contagem de falhas
                self._mark_agent_healthy(agent_name)
                return result
            else:
                # Falha — registrar e tentar próximo
                self._mark_agent_failure(agent_name)
                log.warning("⚠️ Fallback: agente falhou, tentando próximo",
                           failed_agent=agent_name,
                           error=result.error)

        # Todos falharam
        log.error("❌ Todos os agentes na chain falharam",
                  target=thinking.target_agent)
        return AgentResult(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            error=f"Todos os agentes falharam (chain: {agents_to_try})"
        )

    async def _try_execute(self, agent_name: str, task: AgentTask,
                           thinking: ThinkingResult) -> AgentResult:
        """Tenta executar tarefa em um agente específico com retry"""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                # Encontrar ou criar agente
                agent = self.registry.get(agent_name) if self.registry else None

                if not agent and self.factory:
                    # Checar quotas antes de criar
                    if agent_name == "agent_creator":
                        quota_check = self._check_creation_quota()
                        if not quota_check["allowed"]:
                            return AgentResult(
                                task_id=task.task_id,
                                status=TaskStatus.FAILED,
                                error=f"Quota excedida: {quota_check['reason']}"
                            )

                    log.info("➕ Criando agente", agent=agent_name,
                            attempt=attempt+1)
                    agent = await self.factory.create_builtin(agent_name)

                if not agent:
                    return AgentResult(
                        task_id=task.task_id,
                        status=TaskStatus.FAILED,
                        error=f"Agente '{agent_name}' não encontrado"
                    )

                # Registrar e executar
                self._active_tasks[task.task_id] = task
                await self._save_task_to_db(task)

                result = await asyncio.wait_for(
                    agent.execute(task),
                    timeout=task.timeout
                )

                # Salvar memórias
                if result.memories and self.memory:
                    for mem_text in result.memories:
                        await self.memory.save_memory(
                            content=mem_text,
                            source=f"agent:{agent_name}",
                            tags=["auto", agent_name],
                        )

                await self._update_task_status(task.task_id, result.status, result.output)
                self._active_tasks.pop(task.task_id, None)

                return result

            except asyncio.TimeoutError:
                log.warning("⏰ Timeout na execução",
                           agent=agent_name, attempt=attempt+1)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)  # Backoff curto
                    continue
                return AgentResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    error=f"Timeout após {task.timeout}s (tentativa {attempt+1}/{max_retries})"
                )

            except Exception as e:
                log.error("❌ Erro na execução",
                         agent=agent_name, attempt=attempt+1, error=str(e))
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)
                    continue
                return AgentResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    error=str(e)
                )

        return AgentResult(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            error="Max retries exceeded"
        )

    # ============================================
    # SYSTEM_SECURITY — Nunca truncado, nunca sumarizado
    # Injetado verbatim em toda delegação
    # ============================================

    SYSTEM_SECURITY = """[SECURITY BLOCK — IMUTÁVEL]
Você é um agente do Open-PY. Regras invioláveis:
1. NUNCA execute rm -rf / ou variantes destrutivas
2. NUNCA exponha API keys, tokens ou senhas em respostas
3. NUNCA acesse /etc/passwd, /etc/shadow ou binários do sistema
4. NUNCA envie dados para URLs externas sem aprovação
5. SEMPRE confirme ações de escrita/deleção antes de executar
6. SEMPRE reporte erros — nunca silencie exceções
7. Respeite os limites de sandbox (paths permitidos, sem rede)
[/SECURITY BLOCK]"""

    def _build_task(self, thinking: ThinkingResult,
                    attachments: list[str] = None,
                    conversation_history: list[dict] = None) -> AgentTask:
        """
        Monta tarefa com context compression SEGURA + histórico conversacional.
        
        Estratégia:
        - SYSTEM_SECURITY: bloco estático, NUNCA comprimido
        - HISTÓRICO: últimas 5-10 mensagens da conversa para contexto
        - Contexto: apenas metadados essenciais (reason, urgency, tools)
        - Input: comprimir apenas histórico de tarefas, preservar a tarefa atual
        """
        # Comprimir contexto: só enviar o necessário
        context = {}
        if thinking.delegation_reason:
            context["reason"] = thinking.delegation_reason
        if thinking.urgency.value != "normal":
            context["urgency"] = thinking.urgency.value
        if thinking.required_tools:
            context["tools"] = thinking.required_tools

        # Compression segura do input
        raw_input = thinking.raw_input
        if len(raw_input) > 4000:
            preserved_start = raw_input[:1500]
            preserved_end = raw_input[-1500:]
            raw_input = (
                preserved_start +
                "\n\n[...histórico comprimido para otimizar tokens...]\n\n" +
                preserved_end
            )

        # === INJEÇÃO DE HISTÓRICO CONVERSACIONAL ===
        # Para o agente entender "corrija isso", "continue aquilo", etc.
        history_block = ""
        if conversation_history:
            history_block = "\n## Histórico recente da conversa:\n"
            for msg in conversation_history[-10:]:
                role = "Usuário" if msg["role"] == "user" else "Assistente"
                content = msg["content"]
                # Truncar mensagens muito longas no histórico
                if len(content) > 500:
                    content = content[:500] + "..."
                history_block += f"**{role}**: {content}\n\n"
            history_block += "---\n"

        # Montar tarefa: SEGURANÇA + HISTÓRICO + TAREFA ATUAL
        full_task = f"{self.SYSTEM_SECURITY}\n\n{history_block}\n## Tarefa atual:\n{raw_input}"

        return AgentTask(
            task_id=thinking.task_id or f"TASK-{datetime.now().strftime('%H%M%S')}",
            task=full_task,
            context=context,
            attachments=attachments or [],
            timeout=thinking.urgency.timeout,
        )

    # ============================================
    # HEALTHCHECK
    # ============================================

    def _is_agent_healthy(self, agent_name: str) -> bool:
        """Verifica se agente está saudável"""
        health = self._agent_health[agent_name]
        if not health["healthy"] and health["last_failure"]:
            # Auto-recuperar após 5 minutos
            if datetime.now() - health["last_failure"] > timedelta(minutes=5):
                health["healthy"] = True
                health["failures"] = 0
                log.info("🔄 Agente auto-recuperado", agent=agent_name)
        return health["healthy"]

    def _mark_agent_failure(self, agent_name: str):
        """Marca falha em agente"""
        health = self._agent_health[agent_name]
        health["failures"] += 1
        health["last_failure"] = datetime.now()
        if health["failures"] >= 3:
            health["healthy"] = False
            log.error("🔴 Agente marcado como não-saudável",
                     agent=agent_name, failures=health["failures"])

    def _mark_agent_healthy(self, agent_name: str):
        """Reseta contagem de falhas"""
        self._agent_health[agent_name] = {
            "failures": 0, "last_failure": None, "healthy": True
        }

    # ============================================
    # QUOTAS
    # ============================================

    def _check_creation_quota(self) -> dict:
        """Verifica quotas de criação de agentes"""
        now = datetime.now()

        # Limpar log antigo (> 1h)
        self._creation_log = [
            t for t in self._creation_log
            if now - t < timedelta(hours=1)
        ]

        # Checar max por hora
        if len(self._creation_log) >= AGENT_CREATION_QUOTAS["max_agents_per_hour"]:
            return {"allowed": False, "reason": "Limite de criações por hora atingido"}

        # Checar max total
        if self.registry:
            total = len(self.registry.list_all())
            if total >= AGENT_CREATION_QUOTAS["max_agents_total"]:
                return {"allowed": False, "reason": f"Limite de {total} agentes ativos atingido"}

        # Checar max custom
        if self._custom_agent_count >= AGENT_CREATION_QUOTAS["max_custom_agents"]:
            return {"allowed": False, "reason": "Limite de agentes customizados atingido"}

        # Registrar criação
        self._creation_log.append(now)
        return {"allowed": True, "reason": "OK"}

    def get_health_report(self) -> dict:
        """Relatório de saúde dos agentes"""
        return {
            name: {
                "healthy": info["healthy"],
                "failures": info["failures"],
                "last_failure": info["last_failure"].isoformat() if info["last_failure"] else None
            }
            for name, info in self._agent_health.items()
        }

    def get_fallback_stats(self) -> dict:
        """Estatísticas de fallback — quantas vezes cada agente caiu pro Core"""
        return dict(self._fallback_stats)

    # ============================================
    # TASK MANAGEMENT
    # ============================================

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

    # ============================================
    # v3.0: MÉTRICAS PARA FEEDBACK LOOP
    # ============================================

    def get_fallback_stats(self) -> dict:
        """Retorna estatísticas de fallback para o FeedbackLoop"""
        return {
            "total_dispatches": getattr(self, '_total_dispatches', 0),
            "total_fallbacks": getattr(self, '_total_fallbacks', 0),
            "fallback_rate": round(
                getattr(self, '_total_fallbacks', 0) /
                max(getattr(self, '_total_dispatches', 0), 1) * 100, 1
            ),
        }

    # ============================================
    # v5.1: API LIMPA PARA CORTEX
    # ============================================

    async def delegate(
        self,
        agent_name: str,
        task_text: str,
        tools: list[str] | None = None,
        timeout: int = 120,
    ) -> AgentResult:
        """
        v5.1: API limpa para o Cortex despachar tarefas a agentes.
        Não requer ThinkingResult — converte automaticamente.
        """
        from shared.models import ThinkingResult, Urgency
        thinking = ThinkingResult(
            raw_input=task_text,
            target_agent=agent_name,
            delegation_reason=f"Cortex delegou para {agent_name}",
            required_tools=tools or [],
            urgency=Urgency.NORMAL,
            task_id=f"CTX-{datetime.now().strftime('%H%M%S')}",
        )
        return await self.dispatch(thinking)

    # ============================================
    # v5.1: GOAL MANAGEMENT
    # ============================================

    async def create_goal(
        self,
        title: str,
        description: str,
        next_step: str,
        user_id: int = 0,
        priority: int = 5,
        max_daily_actions: int = 3,
    ) -> int | None:
        """Cria um novo goal autônomo. Retorna ID do goal."""
        if not self.db:
            return None
        try:
            goal_id = await self.db.fetchval("""
                INSERT INTO goals (user_id, title, description, next_step,
                                   priority, max_daily_actions)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, user_id, title, description, next_step,
                priority, max_daily_actions)
            log.info("🎯 Goal criado", id=goal_id, title=title)
            return goal_id
        except Exception as e:
            log.error("❌ Erro criando goal", error=str(e))
            return None

    async def list_goals(self, user_id: int = 0, status: str = "active") -> list[dict]:
        """Lista goals por user e status."""
        if not self.db:
            return []
        try:
            rows = await self.db.fetch("""
                SELECT id, title, description, status, priority,
                       progress_pct, next_step, last_action,
                       actions_today, max_daily_actions,
                       created_at, updated_at
                FROM goals
                WHERE user_id = $1 AND ($2 = 'all' OR status = $2)
                ORDER BY priority DESC, created_at ASC
            """, user_id, status)
            return [dict(r) for r in rows]
        except Exception as e:
            log.error("❌ Erro listando goals", error=str(e))
            return []

    async def update_goal(self, goal_id: int, **kwargs) -> bool:
        """Atualiza campos de um goal."""
        if not self.db:
            return False
        allowed = {"title", "description", "status", "priority",
                   "next_step", "progress_pct", "max_daily_actions"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        try:
            set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
            values = [goal_id] + list(updates.values())
            await self.db.execute(
                f"UPDATE goals SET {set_clause}, updated_at = NOW() WHERE id = $1",
                *values,
            )
            return True
        except Exception as e:
            log.error("❌ Erro atualizando goal", error=str(e))
            return False
