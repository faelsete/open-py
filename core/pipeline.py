"""
Open-PY — Execution Pipeline v3.0
Túnel rígido de 6 gates obrigatórios.
Inspirado em: Claude Code QueryEngine + autoCompact circuit breakers.

Fluxo:
  API → [capture] → [memory_recall] → [route] → [prepare] → [execute] → [validate] → Telegram

Cada gate DEVE passar para continuar.
Circuit breaker impede loops infinitos em gates com falha crônica.
"""

import asyncio
import re
import time
from typing import Optional

from shared.models import (
    ThinkingResult, PipelineResult, GateResult, InputType,
    CircuitBreakerState, AgentResult, TaskStatus
)
from shared.config import OpenPYConfig
from shared.logger import get_logger

log = get_logger("pipeline")


class ExecutionPipeline:
    """
    Túnel de execução rígido: 7 gates sequenciais.

    Gate 1 — CAPTURE:       Classifica input (tipo, urgência, continuação)
    Gate 2 — MEMORY_RECALL: Busca semântica por contexto relevante
    Gate 3 — ROUTE:         Decide: Core direto ou delegar para agente?
    Gate 4 — THINK:         Raciocínio neural — planeja ANTES de agir
    Gate 5 — PREPARE:       Monta contexto completo (SECURITY + histórico + memórias)
    Gate 6 — EXECUTE:       Executa seguindo plano neural
    Gate 7 — VALIDATE:      Quality gate — verifica resposta antes do envio
    """

    GATE_NAMES = [
        "capture",
        "memory_recall",
        "route",
        "think",
        "prepare",
        "execute",
        "validate",
    ]

    def __init__(self, config: OpenPYConfig, brain=None, orchestrator=None,
                 memory_manager=None, llm_router=None, validator=None,
                 feedback_loop=None, neural_engine=None):
        self.config = config
        self.brain = brain
        self.orchestrator = orchestrator
        self.memory = memory_manager
        self.llm = llm_router
        self.validator = validator
        self.feedback_loop = feedback_loop
        self.neural = neural_engine  # v4.1: Motor de raciocínio

        # Circuit breakers por gate
        self._breakers: dict[str, CircuitBreakerState] = {
            name: CircuitBreakerState(
                name=name,
                max_failures=config.pipeline.max_gate_failures,
                cooldown_minutes=config.pipeline.gate_cooldown_minutes,
            )
            for name in self.GATE_NAMES
        }

        # Gate timeouts
        self._timeouts = {
            "capture": config.pipeline.gate_timeout_capture,
            "memory_recall": config.pipeline.gate_timeout_memory,
            "route": config.pipeline.gate_timeout_route,
            "think": config.pipeline.gate_timeout_think,
            "prepare": config.pipeline.gate_timeout_prepare,
            "execute": config.pipeline.gate_timeout_execute,
            "validate": config.pipeline.gate_timeout_validate,
        }

        # Métricas por sessão
        self._total_runs = 0
        self._total_failures = 0
        self._gate_timings: dict[str, list[float]] = {n: [] for n in self.GATE_NAMES}

    async def run(self, raw_input: str, input_type: str = "unknown",
                  attachments: list[str] = None, user_id: int = None,
                  conversation_history: list[dict] = None,
                  soul: str = "", essence: str = "") -> PipelineResult:
        """
        Executa todos os 7 gates sequencialmente.
        v4.2: FAST PATH para mensagens simples (saudações, perguntas curtas).
        """
        self._total_runs += 1
        pipeline_start = time.perf_counter()
        gate_results: dict[str, GateResult] = {}
        attachments = attachments or []

        # ============================================
        # v4.2: FAST PATH — Mensagens simples pulam pipeline pesado
        # Padrão Claude Code: resposta rápida sem gates desnecessários
        # ============================================
        if self._is_simple_message(raw_input, attachments):
            log.info("⚡ Fast path ativado", input=raw_input[:30])
            return await self._fast_execute(
                raw_input=raw_input,
                soul=soul,
                conversation_history=conversation_history or [],
                pipeline_start=pipeline_start,
            )

        context = {
            "raw_input": raw_input,
            "input_type": input_type,
            "attachments": attachments,
            "user_id": user_id,
            "history": conversation_history or [],
            "soul": soul,
            "essence": essence,
        }

        for gate_name in self.GATE_NAMES:
            gate_start = time.perf_counter()
            breaker = self._breakers[gate_name]

            # Circuit breaker check
            if not breaker.check():
                log.warning("🔴 Gate skipado (circuit breaker)",
                           gate=gate_name, failures=breaker.consecutive_failures)
                gate_results[gate_name] = GateResult(
                    gate_name=gate_name,
                    passed=True,  # Skip não é falha — pipeline continua
                    skipped=True,
                    skip_reason=f"Circuit breaker tripped ({breaker.consecutive_failures} falhas)",
                    duration_ms=0
                )
                continue

            # Gate opcional desabilitado?
            if gate_name == "memory_recall" and not self.config.pipeline.gate_memory_recall:
                gate_results[gate_name] = GateResult(
                    gate_name=gate_name, passed=True, skipped=True,
                    skip_reason="Desabilitado na config"
                )
                continue
            if gate_name == "validate" and not self.config.pipeline.gate_validate:
                gate_results[gate_name] = GateResult(
                    gate_name=gate_name, passed=True, skipped=True,
                    skip_reason="Desabilitado na config"
                )
                continue
            if gate_name == "think" and not self.config.pipeline.gate_think:
                gate_results[gate_name] = GateResult(
                    gate_name=gate_name, passed=True, skipped=True,
                    skip_reason="Desabilitado na config"
                )
                continue

            try:
                timeout = self._timeouts.get(gate_name, 30)
                gate_method = getattr(self, f"_gate_{gate_name}")
                result_data = await asyncio.wait_for(
                    gate_method(context, gate_results),
                    timeout=timeout
                )

                duration = (time.perf_counter() - gate_start) * 1000
                gate_results[gate_name] = GateResult(
                    gate_name=gate_name,
                    passed=True,
                    data=result_data,
                    duration_ms=round(duration, 2)
                )
                breaker.record_success()
                self._gate_timings[gate_name].append(duration)

                log.debug("✅ Gate passou", gate=gate_name,
                         duration_ms=round(duration, 2))

            except asyncio.TimeoutError:
                duration = (time.perf_counter() - gate_start) * 1000
                breaker.record_failure()
                self._total_failures += 1
                log.error("⏰ Gate timeout", gate=gate_name,
                         timeout=self._timeouts.get(gate_name))

                # Memory recall e validate são soft gates — timeout = skip
                if gate_name in ("memory_recall", "validate", "think"):
                    gate_results[gate_name] = GateResult(
                        gate_name=gate_name, passed=True, skipped=True,
                        skip_reason=f"Timeout ({self._timeouts[gate_name]}s)",
                        duration_ms=round(duration, 2)
                    )
                    continue

                return PipelineResult(
                    success=False,
                    failed_gate=gate_name,
                    error=f"Timeout no gate '{gate_name}' ({self._timeouts[gate_name]}s)",
                    gates=gate_results,
                    total_duration_ms=round((time.perf_counter() - pipeline_start) * 1000, 2)
                )

            except Exception as e:
                duration = (time.perf_counter() - gate_start) * 1000
                breaker.record_failure()
                self._total_failures += 1
                log.error("❌ Gate falhou", gate=gate_name, error=str(e))

                # Soft gates: skip em erro
                if gate_name in ("memory_recall", "validate", "think"):
                    gate_results[gate_name] = GateResult(
                        gate_name=gate_name, passed=True, skipped=True,
                        skip_reason=f"Erro: {str(e)[:100]}",
                        duration_ms=round(duration, 2)
                    )
                    continue

                return PipelineResult(
                    success=False,
                    failed_gate=gate_name,
                    error=f"Erro no gate '{gate_name}': {str(e)}",
                    gates=gate_results,
                    total_duration_ms=round((time.perf_counter() - pipeline_start) * 1000, 2)
                )

        # Pipeline completo com sucesso
        total_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
        response = ""
        task_id = None
        delegated_to = None

        execute_result = gate_results.get("execute")
        if execute_result and execute_result.data:
            response = execute_result.data.get("response", "")
            task_id = execute_result.data.get("task_id")
            delegated_to = execute_result.data.get("delegated_to")

        # Se validate rodou e modificou a resposta, usar a validada
        validate_result = gate_results.get("validate")
        if validate_result and validate_result.data and not validate_result.skipped:
            validated_response = validate_result.data.get("final_response")
            if validated_response:
                response = validated_response

        log.info("✅ Pipeline completo",
                 total_ms=total_ms,
                 gates_passed=len([g for g in gate_results.values() if g.passed]),
                 gates_skipped=len([g for g in gate_results.values() if g.skipped]))

        return PipelineResult(
            success=True,
            response=response,
            gates=gate_results,
            total_duration_ms=total_ms,
            task_id=task_id,
            delegated_to=delegated_to,
        )

    # ============================================
    # v4.2: FAST PATH — Resposta rápida para mensagens simples
    # ============================================

    # Padrões que indicam mensagem simples (não precisa pipeline completo)
    _SIMPLE_PATTERNS = re.compile(
        r'^(oi|olá|ola|hey|hi|hello|e ai|eai|eae|boa noite|bom dia|boa tarde|'
        r'tudo bem|tudo certo|beleza|blz|suave|como vai|ta ai|tá aí|'
        r'obrigado|obrigada|vlw|valeu|brigado|tmj|show|top|massa|dale|'
        r'sim|não|nao|ok|td bem|ta por ai|tá por aí|oe|salve|fala|'
        r'kd vc|cadê|kkk|haha|rs|lol|😂|👍|❤️|🙏|ta vivo|tá vivo|'
        r'to aqui|tô aqui|bora|vamo|vamos|yes|no|yep|nope|tranquilo|'
        r'partiu|tchau|bye|flw|falou|até|ate|xau|fui)\b',
        re.IGNORECASE
    )

    def _is_simple_message(self, raw_input: str, attachments: list) -> bool:
        """Detecta mensagens simples que não precisam do pipeline completo.
        Critérios: curta, sem mídia, sem comando, sem intenção complexa."""
        # Com anexo = nunca é simples
        if attachments:
            return False
        # Comando / = nunca é simples
        if raw_input.strip().startswith('/'):
            return False
        # Muito longa = complexa
        if len(raw_input.strip()) > 60:
            return False
        # Padrão de saudação/confirmação
        if self._SIMPLE_PATTERNS.match(raw_input.strip()):
            return True
        # Mensagem muito curta sem padrão especial (< 15 chars)
        if len(raw_input.strip()) <= 15:
            from core.brain import CODE_PATTERNS, TASK_INTENT_PATTERN
            if not CODE_PATTERNS.search(raw_input) and not TASK_INTENT_PATTERN.search(raw_input):
                return True
        return False

    async def _fast_execute(self, raw_input: str, soul: str,
                            conversation_history: list,
                            pipeline_start: float) -> PipelineResult:
        """Execução rápida: 1 chamada LLM com prompt mínimo e max_tokens baixo.
        Sem memory_recall, sem think, sem validate."""
        from core.brain import build_fast_system_prompt

        if not self.llm:
            return PipelineResult(
                success=False, error="Nenhum provedor LLM configurado.",
                total_duration_ms=0
            )

        system_prompt = build_fast_system_prompt(soul)
        # Usar só as últimas 5 mensagens do histórico (não sobrecarregar)
        recent_history = conversation_history[-5:] if conversation_history else []
        messages = [
            {"role": "system", "content": system_prompt},
            *recent_history,
            {"role": "user", "content": raw_input},
        ]

        try:
            response = await self.llm.complete(
                messages=messages,
                max_tokens=300,   # Resposta curta — é uma saudação
                temperature=0.8,  # Mais natural/humano
            )
            total_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
            log.info("⚡ Fast path completo", total_ms=total_ms,
                     prompt_chars=len(system_prompt))
            return PipelineResult(
                success=True,
                response=response,
                gates={},
                total_duration_ms=total_ms,
            )
        except Exception as e:
            log.warning("⚠️ Fast path falhou, usando pipeline completo", error=str(e))
            # Fallback: pipeline normal (não retorna erro, tenta de novo)
            return PipelineResult(
                success=False,
                error=f"Fast path falhou: {str(e)}",
                total_duration_ms=round((time.perf_counter() - pipeline_start) * 1000, 2)
            )

    # ============================================
    # GATE 1: CAPTURE — Classificação rápida
    # ============================================

    async def _gate_capture(self, ctx: dict, prev: dict) -> dict:
        """Classifica input: tipo, urgência, continuação.
        v4.0: Detecta mídia e FORÇA routing adequado."""
        from core.brain import classify_input_local

        input_type_str = ctx["input_type"]
        has_photo = any(a.endswith(('.jpg', '.png', '.webp', '.gif', '.bmp')) for a in ctx["attachments"])
        has_audio = any(a.endswith(('.ogg', '.mp3', '.wav', '.m4a', '.opus', '.flac')) for a in ctx["attachments"])
        has_video = any(a.endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv')) for a in ctx["attachments"])
        has_pdf = any(a.endswith('.pdf') for a in ctx["attachments"])
        has_xlsx = any(a.endswith(('.xlsx', '.xls', '.csv')) for a in ctx["attachments"])
        has_doc = any(a.endswith(('.pdf', '.docx', '.xlsx', '.txt', '.csv')) for a in ctx["attachments"])

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

        # ============================================
        # v4.0: FORCED ROUTING POR TIPO DE MÍDIA
        # Igual Claude: reconhece o input e FORÇA a tool correta
        # ============================================
        forced_agent = None
        forced_tools = []
        forced_pre_process = None

        if has_audio:
            # Áudio chegou → OBRIGATÓRIO: transcrever primeiro
            forced_agent = "transcriber"
            forced_tools = ["shell_exec", "read_file", "write_file"]
            forced_pre_process = "transcribe_audio"
            log.info("🎤 Áudio detectado → FORÇANDO transcriber")

        elif has_pdf:
            # PDF chegou → OBRIGATÓRIO: ler PDF antes de processar
            forced_tools = ["read_pdf"]
            forced_pre_process = "read_pdf"
            log.info("📄 PDF detectado → FORÇANDO read_pdf")

        elif has_photo:
            # Imagem chegou → OBRIGATÓRIO: agente de visão
            forced_agent = "vision"
            log.info("📷 Imagem detectada → FORÇANDO vision")

        elif has_video:
            # Vídeo chegou → OBRIGATÓRIO: agente de visão
            forced_agent = "vision"
            log.info("🎬 Vídeo detectado → FORÇANDO vision")

        elif has_xlsx:
            # Planilha/CSV → ler antes de processar
            forced_tools = ["read_file"]
            forced_pre_process = "read_spreadsheet"
            log.info("📊 Planilha detectada → FORÇANDO read_file")

        ctx["forced_agent"] = forced_agent
        ctx["forced_tools"] = forced_tools
        ctx["forced_pre_process"] = forced_pre_process

        return {
            "input_type": itype.value,
            "classified": True,
            "forced_agent": forced_agent,
            "forced_tools": forced_tools,
            "forced_pre_process": forced_pre_process,
        }

    # ============================================
    # GATE 2: MEMORY RECALL — Busca semântica
    # ============================================

    async def _gate_memory_recall(self, ctx: dict, prev: dict) -> dict:
        """Busca memórias relevantes ao input atual.
        v4.2: Simplificado — buffer RAM + 1 busca semântica (não 3 queries)."""
        if not self.memory:
            return {"memories": [], "source": "none"}

        query = ctx["raw_input"]
        memories = []

        # 1. Buffer RAM (instantâneo — curto prazo)
        buffer_results = self.memory.search_buffer(query, limit=2)
        for mem in buffer_results:
            content = mem.get("content", "")[:150]
            memories.append({"content": content, "source": "buffer", "weight": 0.9})

        # 2. PostgreSQL semântico (longo prazo — 1 query apenas, limit reduzido)
        try:
            db_results = await self.memory.search(query, mode="hybrid", limit=3)
            for mem in db_results:
                content = mem.get("content", "")[:150]
                similarity = mem.get("similarity", 0.5)
                memories.append({
                    "content": content,
                    "source": "postgresql",
                    "weight": float(similarity) if similarity else 0.5,
                })
        except Exception as e:
            log.warning("⚠️ Busca semântica falhou", error=str(e))

        ctx["memories"] = memories
        return {"memories": memories, "count": len(memories)}

    # ============================================
    # GATE 3: ROUTE — Roteamento inteligente
    # ============================================

    async def _gate_route(self, ctx: dict, prev: dict) -> dict:
        """Decide: Core direto ou delegar para agente?
        v4.0: Respeita forced_agent do CAPTURE gate."""
        if not self.brain:
            return {"target_agent": None, "reason": "brain não disponível"}

        itype = ctx.get("input_type_resolved", InputType.UNKNOWN)

        # v4.0: FORCED ROUTING tem prioridade absoluta
        forced_agent = ctx.get("forced_agent")
        if forced_agent:
            log.info(f"🎯 Rota FORÇADA: {forced_agent}")
            # Criar ThinkingResult mínimo para o forced agent
            from shared.models import ThinkingResult, Urgency
            thinking = ThinkingResult(
                raw_input=ctx["raw_input"],
                input_type=itype,
                target_agent=forced_agent,
                delegation_reason=f"Forçado por tipo de mídia: {itype.value}",
                urgency=Urgency.NORMAL,
            )
            ctx["thinking"] = thinking
            return {
                "target_agent": forced_agent,
                "reason": f"FORÇADO por mídia ({itype.value})",
                "urgency": "normal",
                "forced": True,
            }

        # Roteamento normal via brain
        thinking = await self.brain.think(
            text=ctx["raw_input"],
            input_type=itype,
            attachments=ctx.get("attachments"),
        )

        ctx["thinking"] = thinking
        return {
            "target_agent": thinking.target_agent,
            "reason": thinking.delegation_reason,
            "urgency": thinking.urgency.value,
            "task_id": thinking.task_id,
            "forced": False,
        }

    # ============================================
    # GATE 4: THINK — Raciocínio neural
    #   "Como posso fazer isso? Já fiz antes? Qual melhor caminho?"
    # ============================================

    async def _gate_think(self, ctx: dict, prev: dict) -> dict:
        """Raciocínio neural: planeja ANTES de agir.
        Produz ThoughtChain com steps, ferramentas e verificações."""
        if not self.neural:
            return {"thought_chain": None, "reason": "neural engine não disponível"}

        memories = ctx.get("memories", [])
        attachments = ctx.get("attachments", [])
        itype = ctx.get("input_type_resolved")

        chain = await self.neural.think(
            task=ctx["raw_input"],
            input_type=itype.value if itype else "text",
            memories=memories,
            attachments=attachments,
        )

        ctx["thought_chain"] = chain

        log.info("🧠 Plano neural",
                 steps=chain.total_steps,
                 approach=chain.chosen_approach[:80],
                 confidence=chain.confidence,
                 sandbox=chain.requires_sandbox)

        return {
            "analysis": chain.task_analysis,
            "approach": chain.chosen_approach,
            "steps": chain.total_steps,
            "confidence": chain.confidence,
            "sandbox": chain.requires_sandbox,
            "multi_task": chain.is_multi_task,
            "thinking_ms": chain.thinking_time_ms,
        }

    # ============================================
    # GATE 5: PREPARE — Montar contexto completo
    # ============================================

    async def _gate_prepare(self, ctx: dict, prev: dict) -> dict:
        """Monta contexto completo para execução.
        v4.1: Injeta plano neural no contexto do LLM."""
        from core.brain import build_core_system_prompt

        thinking: ThinkingResult = ctx.get("thinking")
        memories = ctx.get("memories", [])
        thought_chain = ctx.get("thought_chain")

        # System prompt com soul + essence
        system_prompt = build_core_system_prompt(ctx.get("soul", ""), ctx.get("essence", ""))

        # Injetar memórias no contexto (v4.2: máx 3 memórias, conteúdo curto)
        if memories:
            memory_block = "\nContexto relevante:\n"
            for mem in memories[:3]:  # v4.2: 3 ao invés de 8
                content = mem.get("content", "")[:150]  # v4.2: 150 chars max
                memory_block += f"- {content}\n"
            system_prompt += memory_block

        ctx["system_prompt"] = system_prompt

        # Montar mensagens completas (v4.2: últimas 6 mensagens apenas)
        history = ctx.get("history", [])[-6:]
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": ctx["raw_input"]},
        ]
        ctx["messages"] = messages

        return {
            "system_prompt_tokens": len(system_prompt) // 4,
            "history_messages": len(history),
            "memory_injected": len(memories),
            "neural_plan_injected": bool(thought_chain and thought_chain.steps),
        }

    # ============================================
    # GATE 6: EXECUTE — Execução seguindo plano neural
    # ============================================

    async def _gate_execute(self, ctx: dict, prev: dict) -> dict:
        """Executa via Core LLM ou despacha para agente.
        v4.1: Segue plano neural. Pós-execução salva aprendizado."""
        thinking: ThinkingResult = ctx.get("thinking")
        thought_chain = ctx.get("thought_chain")

        # Delegação para agente
        if thinking and thinking.target_agent and self.orchestrator:
            result: AgentResult = await self.orchestrator.dispatch(
                thinking,
                ctx.get("attachments"),
                conversation_history=ctx.get("history", [])[-10:]
            )
            response = result.output or result.error or "Sem resultado"
            success = result.status == TaskStatus.COMPLETED

            # v4.1: Pós-execução — salvar aprendizado
            if thought_chain and self.neural:
                # Marcar steps conforme resultado
                for step in thought_chain.steps:
                    step.status = "done" if success else "failed"
                    step.result = response[:200]
                await self.neural.learn_from_execution(
                    chain=thought_chain,
                    final_result=response[:500],
                    success=success,
                )

            return {
                "response": response,
                "task_id": result.task_id,
                "delegated_to": thinking.target_agent,
                "status": result.status.value,
                "neural_learning": True,
            }

        # Core responde diretamente via LLM
        if self.llm:
            messages = ctx.get("messages", [])
            # v4.2: max_tokens limitado — evita respostas de 800+ tokens pra perguntas simples
            response = await self.llm.complete(messages=messages, max_tokens=1024)

            # v4.1: Pós-execução — salvar aprendizado
            if thought_chain and self.neural:
                for step in thought_chain.steps:
                    step.status = "done"
                await self.neural.learn_from_execution(
                    chain=thought_chain,
                    final_result=response[:500],
                    success=True,
                )

            return {
                "response": response,
                "task_id": None,
                "delegated_to": None,
                "status": "completed",
                "neural_learning": True,
            }

        return {
            "response": "⚠️ Nenhum provedor LLM configurado.",
            "status": "error",
        }

    # ============================================
    # GATE 6: VALIDATE — Quality gate
    # ============================================

    async def _gate_validate(self, ctx: dict, prev: dict) -> dict:
        """Quality gate: verifica resposta antes do envio"""
        execute_data = prev.get("execute", GateResult()).data or {}
        response = execute_data.get("response", "")

        # Skip para respostas curtas
        if len(response) < self.config.validator.min_response_length:
            return {"final_response": response, "validated": False, "reason": "resposta curta"}

        if not self.validator:
            return {"final_response": response, "validated": False, "reason": "validator não configurado"}

        verdict = await self.validator.validate(
            question=ctx["raw_input"],
            response=response,
        )

        if verdict.approved:
            return {
                "final_response": response,
                "validated": True,
                "confidence": verdict.confidence,
            }

        # Resposta rejeitada — tentar refazer?
        log.warning("⚠️ Resposta rejeitada pelo validator",
                    issues=verdict.issues, confidence=verdict.confidence)

        if self.config.validator.max_retries > 0 and self.llm:
            # Refazer com feedback do validator
            retry_prompt = (
                f"Sua resposta anterior foi rejeitada. "
                f"Problemas: {', '.join(verdict.issues)}. "
                f"Sugestão: {verdict.suggestion or 'Seja mais preciso e direto.'}. "
                f"Refaça a resposta para: {ctx['raw_input']}"
            )
            messages = ctx.get("messages", [])[:-1]  # Remove user original
            messages.append({"role": "user", "content": retry_prompt})
            retried = await self.llm.complete(messages=messages)
            return {
                "final_response": retried,
                "validated": True,
                "retried": True,
                "original_issues": verdict.issues,
            }

        # Sem retries — envia com warning
        return {
            "final_response": response,
            "validated": False,
            "issues": verdict.issues,
        }

    # ============================================
    # MÉTRICAS
    # ============================================

    def get_metrics(self) -> dict:
        """Métricas do pipeline para observabilidade"""
        avg_timings = {}
        for name, timings in self._gate_timings.items():
            if timings:
                avg_timings[name] = {
                    "avg_ms": round(sum(timings) / len(timings), 2),
                    "max_ms": round(max(timings), 2),
                    "runs": len(timings),
                }
        return {
            "total_runs": self._total_runs,
            "total_failures": self._total_failures,
            "success_rate": round(
                (self._total_runs - self._total_failures) / max(self._total_runs, 1) * 100, 1
            ),
            "gate_timings": avg_timings,
            "circuit_breakers": {
                name: {
                    "tripped": cb.tripped,
                    "failures": cb.consecutive_failures,
                }
                for name, cb in self._breakers.items()
                if cb.consecutive_failures > 0
            },
        }
