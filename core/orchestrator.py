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
                       attachments: list[str] = None) -> AgentResult:
        """
        Despacha uma tarefa baseado no resultado do Thinking Engine.
        Inclui fallback routing e retry.
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

        # Montar tarefa com context compression
        task = self._build_task(thinking, attachments)

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
                    attachments: list[str] = None) -> AgentTask:
        """
        Monta tarefa com context compression SEGURA.
        
        Estratégia (recomendação do Ori):
        - SYSTEM_SECURITY: bloco estático, NUNCA comprimido
        - Contexto: apenas metadados essenciais (reason, urgency, tools)
        - Input: comprimir apenas histórico de tarefas, preservar a tarefa atual
        - Rebuild: SEGURANÇA (verbatim) + RESUMO_HIERÁRQUICO + TAREFA_ATUAL
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
            # Preservar início (instrução principal) e final (tarefa mais recente)
            # Cortar apenas o meio (histórico antigo)
            preserved_start = raw_input[:1500]
            preserved_end = raw_input[-1500:]
            raw_input = (
                preserved_start +
                "\n\n[...histórico comprimido para otimizar tokens...]\n\n" +
                preserved_end
            )

        # Montar tarefa com bloco de segurança SEMPRE presente
        full_task = f"{self.SYSTEM_SECURITY}\n\n{raw_input}"

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
