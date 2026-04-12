"""
Open-PY v5.0 — Cortex
Core unificado com thinking adaptativo e agentic loop.

Substitui: pipeline.py, engine.py, neural.py
Inspiração: Letta OS model + Claude Code agentic loop + AgentDiet

Fluxo:
1. Classify (sem LLM) → depth_level 0-3
2. Assemble context (adaptativo por depth)
3. Agentic loop (1 chamada LLM, tool loop se necessário)
4. Post-process (background: memória, skill store, feedback)
"""

import asyncio
import hashlib
import json
import re
import time
from typing import AsyncGenerator, Optional

from shared.config import OpenPYConfig
from shared.logger import get_logger
from shared.models import (
    DepthLevel,
    CortexResult,
    CoreMemoryBlock,
    InputType,
)

log = get_logger("cortex")


# ============================================
# CLASSIFICADOR DE PROFUNDIDADE (sem LLM)
# ============================================

# Padrões para depth=0 (resposta instantânea)
_SHALLOW_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(oi|olá|ola|hey|hi|hello|eae|fala|salve|bom dia|boa tarde|boa noite|e ai|e aí)[\s!.?]*$", re.IGNORECASE),
    re.compile(r"^(ok|sim|não|nao|s|n|yes|no|y|valeu|obrigado|obg|vlw|blz|beleza|tmj|top|show|entendi|certo|claro|pode ser)[\s!.?]*$", re.IGNORECASE),
    re.compile(r"^(👍|👎|❤️|🙏|😊|😂|😁|🤝|✅|❌|🔥|💪|🫡|👀|😎)\s*$"),
    re.compile(r"^(tudo bem|como vai|td bem|tdb|como vc está|como está)[\s?!]*$", re.IGNORECASE),
]

# Padrões para depth=3 (raciocínio profundo)
_DEEP_KEYWORDS: list[str] = [
    "arquitetura", "refatorar", "refatora", "migrar", "migração",
    "debug", "depurar", "traceback", "stack trace", "segfault",
    "implementar sistema", "criar projeto", "configurar servidor",
    "analisar código", "review", "otimizar", "pipeline",
    "deploy", "deployment", "ci/cd", "docker", "kubernetes",
    "banco de dados", "schema", "migration", "modelagem",
    "segurança", "vulnerabilidade", "pentest",
]

# Padrões para depth=2 (task com tools)
_TASK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(crie?|criar?|faça|faz|gere?|gerar?|escreva|write|build|make)\s+", re.IGNORECASE),
    re.compile(r"(execute|rodar?|roda|run)\s+", re.IGNORECASE),
    re.compile(r"(instale?|instalar?|pip install|apt|npm)", re.IGNORECASE),
    re.compile(r"(pesquise?|pesquisar?|busque?|buscar?|procure?|search)\s+", re.IGNORECASE),
    re.compile(r"(delete?|deletar?|remova|remover?|apague?|apagar?)\s+", re.IGNORECASE),
    re.compile(r"(leia|ler|read|abrir?|abra)\s+(o\s+)?arquivo", re.IGNORECASE),
    re.compile(r"```", re.IGNORECASE),  # Blocos de código
]

# Tipos de mídia que forçam depth
_MEDIA_DEPTH: dict[str, DepthLevel] = {
    "image": DepthLevel.STANDARD,
    "audio": DepthLevel.STANDARD,
    "video": DepthLevel.STANDARD,
    "document": DepthLevel.STANDARD,
}


def classify_depth(
    text: str,
    input_type: str = "text",
    attachments: Optional[list[str]] = None,
) -> DepthLevel:
    """Classifica profundidade de raciocínio necessária — SEM chamada LLM."""
    # Mídia sempre precisa de pelo menos STANDARD
    if input_type in _MEDIA_DEPTH:
        return _MEDIA_DEPTH[input_type]
    if attachments:
        return DepthLevel.STANDARD

    text_stripped = text.strip()

    # depth=0: saudações e confirmações
    for pattern in _SHALLOW_PATTERNS:
        if pattern.match(text_stripped):
            return DepthLevel.SHALLOW

    text_lower = text_stripped.lower()

    # depth=3: palavras-chave de complexidade alta
    if any(kw in text_lower for kw in _DEEP_KEYWORDS):
        return DepthLevel.DEEP

    # depth=3: texto muito longo (provavelmente task complexa)
    if len(text_stripped) > 500:
        return DepthLevel.DEEP

    # depth=2: padrões de tarefa com tools
    for pattern in _TASK_PATTERNS:
        if pattern.search(text_stripped):
            return DepthLevel.STANDARD

    # default: depth=1 (conversa)
    return DepthLevel.LIGHT


# ============================================
# CORTEX — CORE UNIFICADO
# ============================================

class Cortex:
    """
    Core unificado v5.0 com thinking adaptativo e agentic loop.

    Responsabilidades:
    1. Classificar profundidade do input
    2. Montar contexto adaptativo (menos tokens para msgs simples)
    3. Executar agentic loop com tool-calling
    4. Post-process assíncrono (memória, skills, feedback)
    """

    def __init__(
        self,
        config: OpenPYConfig,
        brain,                    # ThinkingEngine (prompt builders)
        orchestrator,             # Delegação para agentes especializados
        memory_manager,           # Memory v2
        llm_router,               # LLM provider
        validator=None,           # Quality gate (opcional)
        tool_registry=None,       # Registry de tools
        skill_store=None,         # Banco de habilidades
    ):
        self.config = config
        self.cortex_config = config.cortex
        self.brain = brain
        self.orchestrator = orchestrator
        self.memory = memory_manager
        self.llm = llm_router
        self.validator = validator
        self.tools = tool_registry
        self.skills = skill_store

        # Métricas
        self._total_requests = 0
        self._depth_counts: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._total_tokens = 0

    # ============================================
    # ENTRY POINT
    # ============================================

    async def process(
        self,
        raw_input: str,
        input_type: str = "text",
        attachments: Optional[list[str]] = None,
        user_id: Optional[int] = None,
        conversation_history: Optional[list[dict]] = None,
        soul: str = "",
        essence: str = "",
    ) -> AsyncGenerator[dict, None]:
        """
        Ponto de entrada principal — streaming de eventos.

        Yields:
            {"type": "status", "message": "..."} — progresso
            {"type": "thinking", "content": "..."} — reasoning do modelo
            {"type": "tool_call", "name": "...", "args": {...}} — tool em execução
            {"type": "tool_result", "name": "...", "result": "..."} — resultado do tool
            {"type": "final", "cortex_result": CortexResult} — resultado final
        """
        start_time = time.monotonic()
        self._total_requests += 1

        # 1. CLASSIFY — sem LLM, instantâneo
        depth = classify_depth(raw_input, input_type, attachments)
        self._depth_counts[depth.value] += 1

        log.info(
            "🧠 Cortex processando",
            depth=depth.name,
            input_preview=raw_input[:80],
            input_type=input_type,
        )
        yield {"type": "status", "message": f"Analisando (depth={depth.name})..."}

        # 2. CHECK DELEGATION — certos tipos SEMPRE vão para agentes
        delegation_target = self._check_forced_delegation(raw_input, input_type, attachments)

        if delegation_target:
            yield {"type": "status", "message": f"Delegando para {delegation_target}..."}
            async for event in self._delegate_to_agent(
                agent_name=delegation_target,
                raw_input=raw_input,
                input_type=input_type,
                attachments=attachments,
                user_id=user_id,
                conversation_history=conversation_history,
                start_time=start_time,
                depth=depth,
            ):
                yield event
            return

        # 3. SKILL LOOKUP — depth>=2, buscar habilidade reutilizável
        existing_skill = None
        if depth.value >= 2 and self.skills:
            try:
                existing_skill = await self.skills.find_skill(raw_input)
                if existing_skill:
                    log.info("♻️ Skill reutilizável encontrada",
                             skill_id=existing_skill.id,
                             success_count=existing_skill.success_count)
            except Exception as e:
                log.warning("⚠️ Erro buscando skill", error=str(e))

        # 4. ASSEMBLE CONTEXT — adaptativo por depth
        messages = await self._assemble_context(
            depth=depth,
            raw_input=raw_input,
            input_type=input_type,
            conversation_history=conversation_history or [],
            soul=soul,
            essence=essence,
            user_id=user_id,
            existing_skill=existing_skill,
        )

        # 5. AGENTIC LOOP — 1 chamada LLM com tool loop
        tools_called: list[str] = []
        response_text = ""

        model = self._select_model(depth)
        max_tokens = self._get_max_tokens(depth)

        async for event in self._agentic_loop(
            messages=messages,
            depth=depth,
            model=model,
            max_tokens=max_tokens,
        ):
            if event["type"] == "tool_call":
                tools_called.append(event["name"])
            elif event["type"] == "final_text":
                response_text = event["content"]
            else:
                yield event

        duration_ms = (time.monotonic() - start_time) * 1000

        result = CortexResult(
            success=bool(response_text),
            response=response_text,
            depth=depth.value,
            tools_called=tools_called,
            skill_used=str(existing_skill.id) if existing_skill else None,
            total_duration_ms=duration_ms,
        )

        # 6. POST-PROCESS — background
        asyncio.create_task(self._post_process(
            raw_input=raw_input,
            response=response_text,
            depth=depth,
            tools_called=tools_called,
            duration_ms=duration_ms,
            user_id=user_id,
        ))

        yield {
            "type": "final",
            "cortex_result": result,
            "pipeline_result": result,  # backward compat com lifecycle.py
        }

    # ============================================
    # FORCED DELEGATION (media types)
    # ============================================

    def _check_forced_delegation(
        self,
        raw_input: str,
        input_type: str,
        attachments: Optional[list[str]],
    ) -> Optional[str]:
        """Verifica se o input deve ser delegado direto a um agente."""
        # Mídia → agentes especializados
        media_routing: dict[str, str] = {
            "image": "vision",
            "video": "vision",
            "audio": "transcriber",
        }
        if input_type in media_routing:
            return media_routing[input_type]

        text_lower = raw_input.lower().strip()

        # Comandos explícitos de pesquisa
        if any(kw in text_lower for kw in ["pesquise", "pesquisar", "busque na web", "search for"]):
            return "researcher"

        return None

    # ============================================
    # AGENT DELEGATION
    # ============================================

    async def _delegate_to_agent(
        self,
        agent_name: str,
        raw_input: str,
        input_type: str,
        attachments: Optional[list[str]],
        user_id: Optional[int],
        conversation_history: Optional[list[dict]],
        start_time: float,
        depth: DepthLevel,
    ) -> AsyncGenerator[dict, None]:
        """Delega execução para um agente especializado via Orchestrator."""
        if not self.orchestrator:
            yield {
                "type": "final",
                "cortex_result": CortexResult(
                    success=False,
                    error="Orchestrator indisponível",
                    depth=depth.value,
                ),
                "pipeline_result": CortexResult(
                    success=False,
                    error="Orchestrator indisponível",
                    depth=depth.value,
                ),
            }
            return

        try:
            result = await self.orchestrator.delegate(
                task_text=raw_input,
                target_agent=agent_name,
                context={
                    "input_type": input_type,
                    "user_id": user_id,
                    "conversation_history": conversation_history[-6:] if conversation_history else [],
                },
                attachments=attachments or [],
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            response = result.output if result.output else f"⚠️ Agente {agent_name} não retornou resultado."

            cortex_result = CortexResult(
                success=bool(result.output),
                response=response,
                depth=depth.value,
                delegated_to=agent_name,
                task_id=result.task_id,
                total_duration_ms=duration_ms,
                error=result.error,
            )

            yield {
                "type": "final",
                "cortex_result": cortex_result,
                "pipeline_result": cortex_result,
            }

        except Exception as e:
            log.error("❌ Delegação falhou", agent=agent_name, error=str(e))
            duration_ms = (time.monotonic() - start_time) * 1000
            cortex_result = CortexResult(
                success=False,
                response=f"⚠️ Erro ao delegar para {agent_name}: {str(e)}",
                depth=depth.value,
                delegated_to=agent_name,
                total_duration_ms=duration_ms,
                error=str(e),
            )
            yield {
                "type": "final",
                "cortex_result": cortex_result,
                "pipeline_result": cortex_result,
            }

    # ============================================
    # CONTEXT ASSEMBLY (adaptativo por depth)
    # ============================================

    async def _assemble_context(
        self,
        depth: DepthLevel,
        raw_input: str,
        input_type: str,
        conversation_history: list[dict],
        soul: str,
        essence: str,
        user_id: Optional[int] = None,
        existing_skill=None,
    ) -> list[dict]:
        """Monta mensagens para o LLM — adaptativo por profundidade."""
        messages: list[dict] = []

        # === SYSTEM PROMPT (adaptativo) ===
        system_parts: list[str] = []

        if depth == DepthLevel.SHALLOW:
            # depth=0: prompt mínimo absoluto
            system_parts.append(
                "Você é o Open-PY, assistente técnico. "
                "Responda em português brasileiro, de forma breve e direta."
            )
        elif depth == DepthLevel.LIGHT:
            # depth=1: identidade + directives básicas
            persona = self._extract_persona_summary(soul, essence)
            system_parts.append(persona)
        else:
            # depth=2-3: contexto completo
            persona = self._extract_persona_full(soul, essence)
            system_parts.append(persona)

            # Security block — sempre presente em depth>=2
            system_parts.append(self._get_security_block())

        # Core memory blocks (depth>=1)
        if depth.value >= 1 and self.memory:
            core_blocks = self._get_core_memory_prompt(user_id)
            if core_blocks:
                system_parts.append(core_blocks)

        # Memórias semânticas (depth>=1)
        if depth.value >= 1 and self.memory:
            try:
                memories = await self._search_relevant_memories(raw_input, depth)
                if memories:
                    system_parts.append(memories)
            except Exception as e:
                log.warning("⚠️ Busca de memórias falhou", error=str(e))

        # Skill existente como template (depth>=2)
        if existing_skill and depth.value >= 2:
            skill_prompt = (
                f"\n## Habilidade Reutilizável (já funcionou {existing_skill.success_count}x)\n"
                f"Tarefa: {existing_skill.task_description}\n"
                f"Tools: {', '.join(existing_skill.tools_used)}\n"
                f"Use este template como base, adapte se necessário."
            )
            system_parts.append(skill_prompt)

        # Planning template para depth=3
        if depth == DepthLevel.DEEP:
            system_parts.append(
                "\n## Modo de Raciocínio Profundo\n"
                "Antes de agir, pense passo a passo:\n"
                "1. Qual é o objetivo real?\n"
                "2. Quais tools preciso usar e em que ordem?\n"
                "3. Quais riscos e edge cases devo considerar?\n"
                "4. Execute o plano usando as tools disponíveis."
            )

        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        # === CONVERSATION HISTORY ===
        if conversation_history:
            history_limit = 5 if depth.value <= 1 else 10
            for msg in conversation_history[-history_limit * 2:]:
                messages.append(msg)

        # === USER MESSAGE ===
        messages.append({"role": "user", "content": raw_input})

        return messages

    def _extract_persona_summary(self, soul: str, essence: str) -> str:
        """Extrai resumo de 3 linhas da identidade."""
        parts = ["Você é o Open-PY, assistente técnico autônomo."]
        if essence:
            # Primeiras 2 linhas significativas do essence
            lines = [l.strip() for l in essence.split("\n") if l.strip() and not l.startswith("#")]
            parts.extend(lines[:2])
        parts.append("Responda em português brasileiro.")
        return " ".join(parts)

    def _extract_persona_full(self, soul: str, essence: str) -> str:
        """Identidade completa para depth 2-3."""
        parts: list[str] = []
        if essence:
            parts.append(f"## Identidade\n{essence[:1500]}")
        if soul:
            parts.append(f"## Memória Permanente\n{soul[:1500]}")
        if not parts:
            parts.append(
                "Você é o Open-PY, assistente técnico autônomo. "
                "Responda em português brasileiro, direto e objetivo."
            )
        return "\n\n".join(parts)

    def _get_security_block(self) -> str:
        """Bloco de segurança — NUNCA truncado em depth>=2."""
        return (
            "\n## [SECURITY — IMUTÁVEL]\n"
            "- NUNCA execute rm -rf / ou variantes destrutivas\n"
            "- NUNCA exponha credenciais, tokens ou chaves\n"
            "- NUNCA modifique arquivos fora dos diretórios autorizados\n"
            "- SEMPRE peça confirmação antes de ações irreversíveis\n"
            "- SEMPRE valide inputs antes de usar em comandos shell"
        )

    def _get_core_memory_prompt(self, user_id: Optional[int]) -> str:
        """Renderiza core memory blocks como prompt."""
        if not hasattr(self.memory, 'core_memory') or not self.memory.core_memory:
            return ""
        blocks = self.memory.core_memory
        parts: list[str] = ["## Memória Ativa"]
        for block in blocks.values():
            rendered = block.to_prompt()
            if rendered:
                parts.append(rendered)
        if len(parts) == 1:
            return ""
        return "\n".join(parts)

    async def _search_relevant_memories(self, query: str, depth: DepthLevel) -> str:
        """Busca memórias relevantes — quantidade adaptativa por depth."""
        limit = {
            DepthLevel.SHALLOW: 0,
            DepthLevel.LIGHT: 3,
            DepthLevel.STANDARD: 5,
            DepthLevel.DEEP: 8,
        }.get(depth, 3)

        if limit == 0:
            return ""

        results = await self.memory.search(query, mode="hybrid", limit=limit)
        if not results:
            return ""

        parts = ["## Memórias Relevantes"]
        for mem in results:
            content = mem.get("content", "")[:300]
            tags = mem.get("tags", [])
            tag_str = f" [{', '.join(tags[:3])}]" if tags else ""
            parts.append(f"- {content}{tag_str}")
        return "\n".join(parts)

    # ============================================
    # AGENTIC LOOP (tool-calling)
    # ============================================

    async def _agentic_loop(
        self,
        messages: list[dict],
        depth: DepthLevel,
        model: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[dict, None]:
        """
        Loop agentic com tool-calling streaming.
        1 chamada LLM → se pede tool → executa → volta pro LLM → ... → resposta final.
        """
        if not self.llm:
            yield {"type": "final_text", "content": "⚠️ LLM Router indisponível."}
            return

        max_iterations = self.cortex_config.max_tool_iterations
        has_tools = depth.value >= 2 and self.tools

        # Gerar tool schemas se depth >= 2
        tool_schemas: list[dict] = []
        if has_tools:
            # Tools core do sistema (disponíveis para o Cortex direto)
            all_tools = [t["name"] for t in self.tools.list_all()]
            tool_schemas = self.tools.get_schemas_for_agent("cortex", all_tools)

            # Adicionar memory tools
            memory_tools = self._get_memory_tool_schemas()
            tool_schemas.extend(memory_tools)

        iteration = 0
        tools_called_total = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                if has_tools and tool_schemas:
                    result = await self.llm.complete_with_tools(
                        messages=messages,
                        tools=tool_schemas,
                        model=model,
                        tool_choice="auto",
                        max_tokens=max_tokens,
                    )
                else:
                    # Sem tools: chamada direta
                    response_text = await self.llm.complete(
                        messages=messages,
                        model=model,
                        max_tokens=max_tokens,
                    )
                    yield {"type": "final_text", "content": response_text or ""}
                    return

            except Exception as e:
                log.error("❌ Chamada LLM falhou", error=str(e), iteration=iteration)
                yield {"type": "final_text", "content": f"⚠️ Erro na chamada LLM: {str(e)}"}
                return

            # Se não tem tool_calls → texto final
            if not result.get("tool_calls"):
                final_text = result.get("content", "")
                if final_text:
                    yield {"type": "final_text", "content": final_text}
                    return
                if iteration == 1:
                    yield {"type": "final_text", "content": "(Sem resposta do modelo)"}
                    return
                break

            # Processar tool_calls
            assistant_msg = {
                "role": "assistant",
                "content": result.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in result["tool_calls"]
                ],
            }
            messages.append(assistant_msg)

            for tool_call in result["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_call_id = tool_call["id"]

                try:
                    args_str = tool_call["function"]["arguments"]
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str

                    yield {"type": "tool_call", "name": tool_name, "args": args}

                    # Executar tool
                    tool_result = await self._execute_tool(tool_name, args)
                    tools_called_total += 1

                    yield {"type": "tool_result", "name": tool_name, "result": str(tool_result)[:500]}

                except Exception as e:
                    log.error(f"❌ Tool '{tool_name}' erro", error=str(e))
                    tool_result = json.dumps({"error": str(e)})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": str(tool_result),
                })

        # Circuit breaker
        log.warning(f"⚠️ Agentic loop atingiu limite de {max_iterations} iterações")

        last_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                last_content = msg["content"]
                break

        yield {"type": "final_text", "content": last_content or f"(Loop excedeu {max_iterations} iterações)"}

    async def _execute_tool(self, tool_name: str, args: dict) -> str:
        """Executa tool — primeiro checa memory tools, depois registry."""
        # Memory tools especiais (Letta-style)
        if tool_name == "core_memory_read":
            return self._tool_core_memory_read(args.get("block", ""))
        if tool_name == "core_memory_update":
            return self._tool_core_memory_update(args.get("block", ""), args.get("content", ""))
        if tool_name == "archival_search":
            return await self._tool_archival_search(args.get("query", ""))
        if tool_name == "archival_insert":
            return await self._tool_archival_insert(args.get("content", ""), args.get("tags", []))
        if tool_name == "skill_lookup":
            return await self._tool_skill_lookup(args.get("task", ""))

        # Tool registry padrão
        if self.tools:
            # Criar um agent_config mock para o cortex (permissões totais)
            from shared.models import AgentConfig
            cortex_config = AgentConfig(
                agent_id="cortex",
                name="cortex",
                allowed_tools=[t["name"] for t in self.tools.list_all()],
                can_access_network=True,
                can_write_files=True,
                can_exec_commands=True,
            )
            return await self.tools.execute_safe(tool_name, cortex_config, **args)

        return json.dumps({"error": f"Tool '{tool_name}' não encontrada"})

    # ============================================
    # MEMORY TOOLS (Letta-style)
    # ============================================

    def _get_memory_tool_schemas(self) -> list[dict]:
        """Schemas das memory tools para o LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "core_memory_read",
                    "description": "Lê um bloco da memória ativa (persona, user_info, directives)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block": {
                                "type": "string",
                                "enum": ["persona", "user_info", "directives"],
                                "description": "Nome do bloco de memória para ler",
                            }
                        },
                        "required": ["block"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "core_memory_update",
                    "description": "Atualiza um bloco da memória ativa. Use para salvar informações importantes sobre o usuário ou preferências.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block": {
                                "type": "string",
                                "enum": ["user_info", "directives"],
                                "description": "Bloco para atualizar (persona é read-only)",
                            },
                            "content": {
                                "type": "string",
                                "description": "Novo conteúdo do bloco (substitui o anterior)",
                            },
                        },
                        "required": ["block", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "archival_search",
                    "description": "Busca na memória de longo prazo (arquivos, fatos, preferências anteriores)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Busca semântica na memória de longo prazo",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "archival_insert",
                    "description": "Salva uma informação na memória permanente de longo prazo",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Conteúdo a salvar permanentemente",
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Tags para categorizar",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "skill_lookup",
                    "description": "Busca habilidades aprendidas para reutilizar em tarefas similares",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "Descrição da tarefa para buscar skill similar",
                            }
                        },
                        "required": ["task"],
                    },
                },
            },
        ]

    def _tool_core_memory_read(self, block: str) -> str:
        """Lê bloco de core memory."""
        if not self.memory or not hasattr(self.memory, 'core_memory'):
            return json.dumps({"error": "Core memory indisponível"})
        blocks = getattr(self.memory, 'core_memory', {})
        if block not in blocks:
            return json.dumps({"error": f"Bloco '{block}' não existe", "available": list(blocks.keys())})
        return json.dumps({"block": block, "content": blocks[block].content})

    def _tool_core_memory_update(self, block: str, content: str) -> str:
        """Atualiza bloco de core memory."""
        if not self.memory or not hasattr(self.memory, 'core_memory'):
            return json.dumps({"error": "Core memory indisponível"})
        if block == "persona":
            return json.dumps({"error": "Bloco 'persona' é read-only"})
        blocks = getattr(self.memory, 'core_memory', {})
        if block not in blocks:
            return json.dumps({"error": f"Bloco '{block}' não existe"})
        success = blocks[block].update(content)
        if success:
            log.info("🧠 Core memory atualizada", block=block, chars=len(content))
            # v5.0: Persistir no PostgreSQL em background
            if hasattr(self.memory, 'save_core_memory'):
                asyncio.create_task(self.memory.save_core_memory())
            return json.dumps({"status": "updated", "block": block})
        return json.dumps({"error": f"Conteúdo excede limite ({blocks[block].max_chars} chars)"})

    async def _tool_archival_search(self, query: str) -> str:
        """Busca na memória de longo prazo."""
        if not self.memory:
            return json.dumps({"error": "Memory indisponível"})
        results = await self.memory.search(query, mode="hybrid", limit=5)
        if not results:
            return json.dumps({"results": [], "message": "Nenhuma memória encontrada"})
        return json.dumps({"results": [
            {"content": r.get("content", "")[:300], "tags": r.get("tags", [])}
            for r in results
        ]}, ensure_ascii=False)

    async def _tool_archival_insert(self, content: str, tags: Optional[list[str]] = None) -> str:
        """Salva na memória permanente."""
        if not self.memory:
            return json.dumps({"error": "Memory indisponível"})
        await self.memory.save_memory(
            content=content,
            content_type="fact",
            source="cortex",
            tags=tags or [],
            importance=7,
        )
        return json.dumps({"status": "saved", "content_preview": content[:100]})

    async def _tool_skill_lookup(self, task: str) -> str:
        """Busca habilidade aprendida."""
        if not self.skills:
            return json.dumps({"error": "Skill store indisponível"})
        skill = await self.skills.find_skill(task)
        if not skill:
            return json.dumps({"found": False, "message": "Nenhuma skill similar encontrada"})
        return json.dumps({
            "found": True,
            "task": skill.task_description,
            "tools": skill.tools_used,
            "success_count": skill.success_count,
            "steps": skill.steps_json[:5],  # Primeiros 5 steps como preview
        }, ensure_ascii=False)

    # ============================================
    # MODEL/TOKEN SELECTION
    # ============================================

    def _select_model(self, depth: DepthLevel) -> Optional[str]:
        """Seleciona modelo baseado no depth level."""
        if depth == DepthLevel.SHALLOW and self.cortex_config.depth_0_model:
            return self.cortex_config.depth_0_model
        if depth == DepthLevel.DEEP and self.cortex_config.depth_3_model:
            return self.cortex_config.depth_3_model
        return None  # usa padrão do router

    def _get_max_tokens(self, depth: DepthLevel) -> int:
        """Retorna max_tokens baseado no depth level."""
        return {
            DepthLevel.SHALLOW: self.cortex_config.depth_0_max_tokens,
            DepthLevel.LIGHT: self.cortex_config.depth_1_max_tokens,
            DepthLevel.STANDARD: self.cortex_config.depth_2_max_tokens,
            DepthLevel.DEEP: self.cortex_config.depth_3_max_tokens,
        }.get(depth, 1024)

    # ============================================
    # POST-PROCESSING (não bloqueia resposta)
    # ============================================

    async def _post_process(
        self,
        raw_input: str,
        response: str,
        depth: DepthLevel,
        tools_called: list[str],
        duration_ms: float,
        user_id: Optional[int] = None,
    ):
        """Post-processing assíncrono — salva memória, skills, feedback."""
        try:
            # 1. Buffer de interação na memória
            if self.memory:
                await self.memory.buffer_interaction(raw_input, response)

            # 2. Salvar skill se foi task com tools bem-sucedida
            if tools_called and depth.value >= 2 and self.skills:
                task_hash = hashlib.sha256(raw_input.lower().strip().encode()).hexdigest()[:16]
                await self.skills.save_skill(
                    task_description=raw_input[:500],
                    task_hash=task_hash,
                    tools_used=tools_called,
                    steps_json=[],  # Simplificado por agora
                    success=True,
                    duration_seconds=duration_ms / 1000,
                )

        except Exception as e:
            log.error("⚠️ Post-process falhou", error=str(e))

    # ============================================
    # METRICS
    # ============================================

    def get_metrics(self) -> dict:
        """Estatísticas do Cortex."""
        return {
            "total_requests": self._total_requests,
            "depth_distribution": dict(self._depth_counts),
            "total_tokens_estimated": self._total_tokens,
        }
