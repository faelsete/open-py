"""
Open-PY v4.0 — Agent Base
Classe base com Tool-Calling Loop: LLM pede tool → executa → retorna → LLM continua.
Inspirado no padrão Claude Code CLI (agentic loop).
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

# Max iterações do tool loop (circuit breaker)
MAX_TOOL_ITERATIONS = 15


class AgentBase:
    """
    Classe base para todos os agentes Open-PY.
    
    v4.0: Implementa Tool-Calling Loop completo:
    1. Monta schemas das tools permitidas
    2. Chama LLM com tools=schemas
    3. Se LLM retorna tool_calls → executa cada tool → append resultado
    4. Volta pro LLM com resultados
    5. Repete até LLM retornar texto final (sem tool_calls)
    """

    def __init__(self, config: AgentConfig, llm_router=None,
                 tool_registry=None):
        self.config = config
        self.llm = llm_router
        self.tool_registry = tool_registry
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
        v4.0: Executa tarefa com Tool-Calling Loop.
        O LLM decide quais tools usar. O agente EXECUTA de verdade.
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

            # v4.0: Modelo independente por agente
            model = self.config.model if self.config.model != "default" else None
            
            # v4.0: Gerar schemas das tools permitidas
            tool_schemas = []
            if self.tool_registry and self.config.allowed_tools:
                tool_schemas = self.tool_registry.get_schemas_for_agent(
                    self.agent_id, self.config.allowed_tools
                )

            has_tools = bool(tool_schemas)
            log.info("🤖 Agente executando",
                     agent=self.name, model=model or "default",
                     tools=len(tool_schemas),
                     task_preview=task.task[:80])

            # Montar mensagens iniciais
            messages = [
                {"role": "system", "content": self.config.system_prompt},
            ]

            # Injetar histórico de conversa se disponível
            if task.context and task.context.get("conversation_history"):
                history = task.context["conversation_history"]
                if isinstance(history, list):
                    messages.extend(history[-6:])

            messages.append({"role": "user", "content": self._build_task_prompt(task)})

            # ============================================
            # v4.0: TOOL-CALLING LOOP
            # ============================================
            if has_tools:
                response_text = await self._tool_calling_loop(
                    messages=messages,
                    tool_schemas=tool_schemas,
                    model=model,
                )
            else:
                # Sem tools: chamada direta (comportamento v3)
                response_text = await self.llm.complete(
                    messages=messages, model=model
                )

            duration = (datetime.now() - start_time).total_seconds()
            self.status = AgentStatus.IDLE
            log.info("✅ Agente concluiu",
                     agent=self.name, duration=f"{duration:.1f}s")

            return AgentResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                output=response_text,
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

    async def _tool_calling_loop(self, messages: list, tool_schemas: list,
                                  model: str = None) -> str:
        """
        v4.0: Loop agentic completo.
        
        LLM → tool_calls → execute → result → LLM → ... → texto final
        
        Baseado no padrão do Claude Code CLI:
        - Max iterações como circuit breaker
        - Cada tool call é executada via execute_safe (com permissões)
        - Resultados são adicionados como mensagens "tool" 
        - Loop termina quando LLM retorna texto sem tool_calls
        """
        iteration = 0
        tool_calls_total = 0

        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1

            # Chamar LLM com tools
            result = await self.llm.complete_with_tools(
                messages=messages,
                tools=tool_schemas,
                model=model,
                tool_choice="auto",
            )

            # Se não tem tool_calls → texto final
            if not result.get("tool_calls"):
                final_text = result.get("content", "")
                if final_text:
                    log.info(f"🏁 Tool loop concluído",
                             agent=self.name,
                             iterations=iteration,
                             tool_calls=tool_calls_total)
                    return final_text
                
                # LLM retornou vazio sem tool_calls — fallback
                if iteration == 1:
                    return "(Agente não produziu resposta)"
                break

            # Processar cada tool_call
            # Primeiro: adicionar a mensagem do assistant com tool_calls
            assistant_msg = {"role": "assistant", "content": result.get("content") or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    }
                }
                for tc in result["tool_calls"]
            ]
            messages.append(assistant_msg)

            # Executar cada tool e adicionar resultado
            for tool_call in result["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_call_id = tool_call["id"]
                
                try:
                    # Parse argumentos
                    args_str = tool_call["function"]["arguments"]
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str

                    log.info(f"🔧 Tool call: {tool_name}",
                             agent=self.name, args=str(args)[:150])

                    # Executar via registry (com permission check)
                    if self.tool_registry:
                        tool_result = await self.tool_registry.execute_safe(
                            tool_name=tool_name,
                            agent_config=self.config,
                            **args,
                        )
                    else:
                        tool_result = json.dumps({"error": "No tool registry"})

                    tool_calls_total += 1

                except Exception as e:
                    log.error(f"❌ Tool '{tool_name}' erro",
                              agent=self.name, error=str(e))
                    tool_result = json.dumps({"error": str(e)})

                # Adicionar resultado como mensagem "tool"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": str(tool_result),
                })

        # Circuit breaker: loop excedeu max
        log.warning(f"⚠️ Tool loop atingiu limite de {MAX_TOOL_ITERATIONS} iterações",
                    agent=self.name)
        
        # Pegar último conteúdo disponível
        last_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                last_content = msg["content"]
                break
        
        return last_content or f"(Tool loop excedeu {MAX_TOOL_ITERATIONS} iterações)"

    def _build_task_prompt(self, task: AgentTask) -> str:
        """Monta o prompt completo para o agente"""
        prompt = task.task

        if task.context:
            prompt += f"\n\nContexto adicional:\n"
            for k, v in task.context.items():
                if k == "conversation_history":
                    continue  # Já injetado como mensagens
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
