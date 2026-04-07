import asyncio
import time
from typing import AsyncGenerator
import re

from shared.models import (
    ThinkingResult, PipelineResult, GateResult, InputType,
    CircuitBreakerState, AgentResult, TaskStatus
)
from shared.config import OpenPYConfig
from shared.logger import get_logger

log = get_logger("engine")

class QueryEngine:
    """
    Open-PY — Query Engine v4.0
    Substitui o pipeline rígido por um loop assíncrono baseado em streaming.
    Inspirado no Claude Code QueryEngine.
    """

    def __init__(self, config: OpenPYConfig, brain=None, orchestrator=None,
                 memory_manager=None, llm_router=None, validator=None,
                 feedback_loop=None, neural_engine=None, tool_registry=None):
        self.config = config
        self.brain = brain
        self.orchestrator = orchestrator
        self.memory = memory_manager
        self.llm = llm_router
        self.validator = validator
        self.feedback_loop = feedback_loop
        self.neural = neural_engine
        self.tool_registry = tool_registry
        
        self._total_runs = 0
        self._total_failures = 0

    def _is_simple_message(self, text: str, attachments: list) -> bool:
        if attachments:
            return False
        t = text.strip().lower()
        return t in ["oi", "olá", "ola", "tudo bem?", "ping", "bom dia", "boa noite", "boa tarde", "teste"]

    async def _fast_execute(self, raw_input: str, soul: str,
                            conversation_history: list,
                            pipeline_start: float) -> AsyncGenerator[dict, None]:
        """Execução rápida com streaming para mensagens simples."""
        from core.brain import build_fast_system_prompt

        if not self.llm:
            yield {"type": "error", "message": "Nenhum provedor LLM configurado."}
            return

        system_prompt = build_fast_system_prompt(soul)
        recent_history = conversation_history[-5:] if conversation_history else []
        messages = [
            {"role": "system", "content": system_prompt},
            *recent_history,
            {"role": "user", "content": raw_input},
        ]

        yield {"type": "status", "message": "⚡ Respondendo rápido..."}
        
        full_response = ""
        try:
            async for chunk in self.llm.stream_complete(
                messages=messages, max_tokens=300, temperature=0.8, thinking=False
            ):
                full_response += chunk
                yield {"type": "chunk", "text": chunk}
            
            total_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
            log.info("⚡ Fast path completo", total_ms=total_ms)
            
            if self.memory:
                asyncio.create_task(self.memory.buffer_interaction(raw_input, full_response))
            
            yield {
                "type": "final",
                "pipeline_result": PipelineResult(
                    success=True,
                    response=full_response,
                    gates={},
                    total_duration_ms=total_ms,
                )
            }
        except Exception as e:
            log.warning("⚠️ Fast path falhou", error=str(e))
            yield {"type": "error", "message": f"Falha no Fast Path: {str(e)}"}

    async def run(self, raw_input: str, input_type: str = "unknown",
                  attachments: list[str] = None, user_id: int = None,
                  conversation_history: list[dict] = None,
                  soul: str = "", essence: str = "") -> AsyncGenerator[dict, None]:
        """
        Executa o fluxo principal, emitindo eventos de status, chunks e o resultado final.
        """
        self._total_runs += 1
        pipeline_start = time.perf_counter()
        attachments = attachments or []

        if self._is_simple_message(raw_input, attachments):
            # Fast path (Streaming)
            async for event in self._fast_execute(raw_input, soul, conversation_history, pipeline_start):
                yield event
            return

        ctx = {
            "raw_input": raw_input,
            "input_type": input_type,
            "attachments": attachments,
            "user_id": user_id,
            "history": conversation_history or [],
            "soul": soul,
            "essence": essence,
        }

        # GATE: CAPTURE
        yield {"type": "status", "message": "🔎 Analisando requisição..."}
        from core.brain import classify_input_local
        
        input_type_str = ctx["input_type"]
        has_photo = any(a.endswith(('.jpg', '.png', '.webp', '.gif', '.bmp')) for a in attachments)
        has_audio = any(a.endswith(('.ogg', '.mp3', '.wav', '.m4a', '.opus', '.flac')) for a in attachments)
        has_video = any(a.endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv')) for a in attachments)
        has_pdf = any(a.endswith('.pdf') for a in attachments)
        has_xlsx = any(a.endswith(('.xlsx', '.xls', '.csv')) for a in attachments)
        has_doc = any(a.endswith(('.pdf', '.docx', '.xlsx', '.txt', '.csv')) for a in attachments)

        try:
            itype = InputType(input_type_str)
        except ValueError:
            itype = InputType.UNKNOWN

        if itype == InputType.UNKNOWN:
            itype = classify_input_local(
                ctx["raw_input"],
                has_photo=has_photo,
                has_audio=has_audio,
                has_video=has_video,
                has_document=has_doc,
            )
        ctx["input_type_resolved"] = itype

        forced_agent = None
        if has_audio:
            forced_agent = "transcriber"
        elif has_photo or has_video:
            forced_agent = "vision"

        ctx["forced_agent"] = forced_agent

        # GATE: MEMORY RECALL
        yield {"type": "status", "message": "🧠 Buscando contexto..."}
        memories = []
        if self.memory:
            buffer_results = self.memory.search_buffer(raw_input, limit=2)
            for mem in buffer_results:
                memories.append({"content": mem.get("content", "")[:300], "source": "buffer"})
            
            try:
                db_results = await self.memory.search(raw_input, mode="hybrid", limit=3)
                for mem in db_results:
                    memories.append({"content": mem.get("content", "")[:300], "source": "postgresql"})
            except Exception as e:
                log.warning("⚠️ Busca semântica falhou", error=str(e))
        
        ctx["memories"] = memories

        # GATE: ROUTE
        yield {"type": "status", "message": "🧭 Roteando..."}
        if forced_agent:
            target_agent = forced_agent
            thinking = ThinkingResult(
                raw_input=raw_input,
                input_type=itype,
                target_agent=forced_agent,
                delegation_reason="Forçado por mídia",
                urgency="normal"
            )
        else:
            if self.brain:
                thinking = await self.brain.think(
                    text=raw_input,
                    input_type=itype,
                    attachments=attachments
                )
            else:
                thinking = ThinkingResult(raw_input=raw_input, input_type=itype, target_agent=None)
            target_agent = thinking.target_agent

        ctx["thinking"] = thinking

        # GATE: PREPARE (Context builder)
        yield {"type": "status", "message": "⚙️ Preparando execução..."}
        from core.brain import build_core_system_prompt
        system_prompt = build_core_system_prompt(soul, essence, memories)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(ctx["history"][-8:])
        messages.append({"role": "user", "content": raw_input})

        # GATE: EXECUTE
        yield {"type": "status", "message": "🧠 Processando resposta..."}
        
        full_response = ""
        task_id = None
        status = "completed"

        if target_agent and self.orchestrator:
            # Delegate to agent (Agents are not streaming yet in this version, so we wait)
            yield {"type": "status", "message": f"🤖 Delegado para: {target_agent}..."}
            result = await self.orchestrator.dispatch(
                thinking,
                attachments,
                conversation_history=ctx["history"][-8:]
            )
            full_response = result.output or result.error or "Sem resultado"
            task_id = result.task_id
            status = result.status.value
            
            # Send chunks for agent output just fake-streaming so UI works
            chunk_size = 50
            for i in range(0, len(full_response), chunk_size):
                yield {"type": "chunk", "text": full_response[i:i+chunk_size]}
                await asyncio.sleep(0.05)

        elif self.llm:
            try:
                import json
                
                # Definir ferramentas autônomas padrão para o Core
                tools_schemas = []
                allowed_core_tools = [
                    "web_search", "read_file", "write_file", "list_files", 
                    "delete_file", "shell_exec", "python_exec", "system_info",
                    "http_get"
                ]
                
                class CoreAgentConfig:
                    name = "Core"
                    allowed_tools = allowed_core_tools
                    can_access_network = True
                    can_write_files = True
                    can_exec_commands = True
                    allowed_paths = []  # Bypass de restrição de diretório para o Core
                
                core_config = CoreAgentConfig()

                if self.tool_registry:
                    tools_schemas = self.tool_registry.get_schemas_for_agent("core", allowed_core_tools)

                is_done = False
                while not is_done:
                    has_tool_calls = False
                    
                    # Usa stream_complete_with_tools para permitir function calling
                    async for event in self.llm.stream_complete_with_tools(
                        messages=messages, tools=tools_schemas, max_tokens=4096, thinking=True
                    ):
                        if event["type"] == "content":
                            chunk = event["content"]
                            full_response += chunk
                            yield {"type": "chunk", "text": chunk}
                            
                        elif event["type"] == "tool_calls":
                            has_tool_calls = True
                            tool_calls = event["tool_calls"]
                            
                            # Registrar a chamada no histórico
                            messages.append({
                                "role": "assistant",
                                "content": None,
                                "tool_calls": tool_calls
                            })
                            
                            # Executar ferramentas
                            for call in tool_calls:
                                tid = call["id"]
                                fname = call["function"]["name"]
                                fargs_str = call["function"]["arguments"]
                                yield {"type": "status", "message": f"🔧 Executando {fname}..."}
                                
                                try:
                                    kwargs = json.loads(fargs_str) if fargs_str else {}
                                    if self.tool_registry:
                                        result_str = await self.tool_registry.execute_safe(fname, core_config, **kwargs)
                                    else:
                                        result_str = '{"error": "Registry indisponível"}'
                                except Exception as e:
                                    result_str = json.dumps({"error": str(e)}, ensure_ascii=False)
                                    
                                # O LLM receberá os resultados como papel "tool"
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tid,
                                    "name": fname,
                                    "content": result_str
                                })
                            
                            break  # Sai do async for para que o loop while emita uma nova requisição LLM com o contexto
                            
                    if not has_tool_calls:
                        is_done = True

            except Exception as e:
                log.error("Erro no streaming com tools", error=str(e))
                full_response += f"\n⚠️ Erro ao gerar resposta: {str(e)}"
                yield {"type": "error", "message": full_response}
                status = "error"
        else:
            full_response = "⚠️ Nenhum provedor LLM configurado."
            status = "error"
            yield {"type": "error", "message": full_response}

        total_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
        
        if self.memory and status != "error":
            asyncio.create_task(self.memory.buffer_interaction(raw_input, full_response))

        yield {
            "type": "final",
            "pipeline_result": PipelineResult(
                success=(status != "error"),
                response=full_response,
                gates={},
                task_id=task_id,
                delegated_to=target_agent,
                total_duration_ms=total_ms
            )
        }
