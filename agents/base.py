"""
Open-PY — Agent Base
Classe base para todos os agentes. Cada agente roda como processo isolado.
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime
from typing import Optional

from shared.models import AgentConfig, AgentStatus, AgentTask, AgentResult, TaskStatus
from shared.logger import get_logger

log = get_logger("agent")


class AgentBase:
    """
    Classe base para todos os agentes Open-PY.
    Cada agente roda em processo isolado (com ou sem bwrap sandbox).
    Comunicação com Core via stdin/stdout (JSON-RPC simplificado).
    """

    def __init__(self, config: AgentConfig, llm_router=None):
        self.config = config
        self.llm = llm_router
        self.status = AgentStatus.IDLE
        self._process: Optional[subprocess.Popen] = None

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def name(self) -> str:
        return self.config.name

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Executa uma tarefa usando LLM diretamente (modo inline).
        v3.0: Cada agente usa seu modelo configurado + injeta histórico.
        """
        self.status = AgentStatus.RUNNING
        start_time = datetime.now()

        try:
            if not self.llm:
                return AgentResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    error="Nenhum provedor LLM disponível"
                )

            # v3.0: Modelo independente por agente
            model = self.config.model if self.config.model != "default" else None
            log.info("🤖 Agente executando",
                     agent=self.name, model=model or "default",
                     task_preview=task.task[:80])

            # Montar mensagens para o LLM
            messages = [
                {"role": "system", "content": self.config.system_prompt},
            ]

            # v3.0: Injetar histórico de conversa se disponível
            if task.context and task.context.get("conversation_history"):
                history = task.context["conversation_history"]
                if isinstance(history, list):
                    messages.extend(history[-6:])  # Últimas 3 trocas

            messages.append({"role": "user", "content": self._build_task_prompt(task)})

            # Chamar LLM com modelo específico do agente
            response = await self.llm.complete(messages=messages, model=model)

            duration = (datetime.now() - start_time).total_seconds()
            self.status = AgentStatus.IDLE
            log.info("✅ Agente concluiu",
                     agent=self.name, duration=f"{duration:.1f}s")

            return AgentResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                output=response,
                duration_seconds=duration,
            )

        except Exception as e:
            self.status = AgentStatus.ERROR
            duration = (datetime.now() - start_time).total_seconds()
            log.error("Erro na execução do agente",
                      agent=self.name, error=str(e))
            return AgentResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                duration_seconds=duration,
            )

    def _build_task_prompt(self, task: AgentTask) -> str:
        """Monta o prompt completo para o agente"""
        prompt = task.task

        if task.context:
            prompt += f"\n\nContexto adicional:\n"
            for k, v in task.context.items():
                prompt += f"- {k}: {v}\n"

        if task.attachments:
            prompt += f"\n\nArquivos disponíveis:\n"
            for att in task.attachments:
                prompt += f"- {att}\n"

        return prompt

    async def stop(self):
        """Para o agente"""
        self.status = AgentStatus.STOPPED
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def to_dict(self) -> dict:
        """Serializa info do agente"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.config.description,
            "type": self.config.agent_type,
            "status": self.status.value,
            "model": self.config.model,
            "tools": self.config.allowed_tools,
        }
