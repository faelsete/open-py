"""
Open-PY — Thinking Engine (Cérebro)
v5.0: Funções puras de classificação e construção de prompt.
O Cortex (cortex.py) é agora o motor principal de raciocínio.
ThinkingEngine mantida para backward compat com lifecycle.py e pipeline.py.
"""

import re
from datetime import datetime
from typing import Optional

from shared.models import ThinkingResult, InputType, Urgency, AgentTask
from shared.logger import get_logger
from shared.config import get_config

log = get_logger("brain")


# ============================================
# SYSTEM PROMPTS
# ============================================


def build_fast_system_prompt(soul: str) -> str:
    """System prompt MÍNIMO para respostas rápidas (saudações, perguntas simples).
    Usa apenas as 3 primeiras linhas do soul.md (identidade) sem protocolo pesado."""
    # Pegar só a identidade do soul (primeiras linhas não-vazias)
    soul_lines = [l.strip() for l in soul.split('\n') if l.strip()][:5]
    soul_identity = '\n'.join(soul_lines)
    return f"""{soul_identity}

Responda de forma natural, concisa e calorosa em português brasileiro.
Seja direto e humano. NÃO use listas, protocolos ou formatação complexa.
Para saudações responda brevemente como um amigo."""

def build_core_system_prompt(soul: str, essence: str, memories: list[dict] = None) -> str:
    """System prompt ENXUTO para o Core.
    v4.2: A memória semântica cuida do contexto. O prompt só define identidade e tom.
    Protocolo de 4 camadas removido (o pipeline já faz isso em código)."""
    # Extrair só as primeiras linhas relevantes (identidade)
    soul_lines = [l.strip() for l in soul.split('\n') if l.strip() and not l.startswith('#')][:8]
    soul_identity = '\n'.join(soul_lines)

    essence_lines = [l.strip() for l in essence.split('\n') if l.strip() and not l.startswith('#')][:5]
    essence_summary = '\n'.join(essence_lines)

    memory_context = ""
    if memories:
        memory_context = "\n\n=== CONTEXTO DA MEMÓRIA ===\n" + "\n".join([m.get("content", "") for m in memories])

    return f"""{essence_summary}

{soul_identity}{memory_context}

Regras: responda em português brasileiro, seja direto e natural. Não invente informações. Use as memórias fornecidas como contexto."""


# ============================================
# CLASSIFICAÇÃO RÁPIDA (SEM LLM)
# ============================================

# Padrões regex para classificação local
CODE_PATTERNS = re.compile(
    r'(```|def |class |import |function |const |var |let |error|bug|debug|script|'
    r'traceback|exception|syntax|compile|npm |pip |git |docker |bash |'
    r'TypeError|ValueError|IndentationError|ModuleNotFoundError)',
    re.IGNORECASE
)

TASK_INTENT_PATTERN = re.compile(
    r'\b(crie|fa[çc]a|pesquise|busque|analise|procure|gere|implemente)\b',
    re.IGNORECASE
)

COMMAND_PATTERN = re.compile(r'^/')


def classify_input_local(text: str, has_photo: bool = False,
                         has_audio: bool = False, has_video: bool = False,
                         has_document: bool = False) -> InputType:
    """
    Classificação rápida SEM usar LLM.
    Retorna InputType ou UNKNOWN se não conseguir classificar.
    """
    # Mídia tem prioridade absoluta
    if has_photo:
        return InputType.IMAGE
    if has_audio:
        return InputType.AUDIO
    if has_video:
        return InputType.VIDEO
    if has_document:
        return InputType.DOCUMENT

    if not text:
        return InputType.UNKNOWN

    # Comando do Telegram
    if COMMAND_PATTERN.match(text.strip()):
        return InputType.COMMAND

    # Código detectado por padrões
    if CODE_PATTERNS.search(text):
        return InputType.CODE

    # Texto genérico
    return InputType.TEXT


# ============================================
# CLASSIFICAÇÃO VIA LLM (FALLBACK BARATO)
# ============================================

CLASSIFICATION_PROMPT = """Classifique em UMA categoria:
TEXT | IMAGE | AUDIO | VIDEO | CODE | COMMAND | DOCUMENT

Mensagem: "{message}"

Responda APENAS a categoria."""


async def classify_input_llm(text: str, llm_router) -> InputType:
    """Classificação via LLM para casos ambíguos"""
    try:
        response = await llm_router.complete(
            messages=[{"role": "user", "content": CLASSIFICATION_PROMPT.format(message=text[:200])}],
            max_tokens=10,
            temperature=0.0
        )
        result = response.strip().upper()
        return InputType(result.lower()) if result.lower() in InputType.__members__ else InputType.TEXT
    except Exception:
        return InputType.TEXT


# ============================================
# THINKING ENGINE
# ============================================

class ThinkingEngine:
    """Motor de raciocínio em 4 camadas"""

    def __init__(self, llm_router=None, memory_manager=None, agent_registry=None):
        self.llm = llm_router
        self.memory = memory_manager
        self.registry = agent_registry
        self._task_counter = 0

    def _next_task_id(self) -> str:
        self._task_counter += 1
        return f"TASK-{self._task_counter:04d}"

    async def think(self, text: str, input_type: InputType = InputType.UNKNOWN,
                    attachments: list[str] = None) -> ThinkingResult:
        """
        Executa as 4 camadas de raciocínio.
        Retorna ThinkingResult com decisão completa.
        """
        result = ThinkingResult(raw_input=text, timestamp=datetime.now())

        # =========== CAMADA 1: CAPTURA ===========
        log.info("🧠 Camada 1: Captura e Classificação", input=text[:100])

        if input_type == InputType.UNKNOWN:
            input_type = classify_input_local(text)

        result.input_type = input_type
        result.urgency = self._assess_urgency(text, input_type)
        result.is_continuation = await self._check_continuation(text)

        # =========== CAMADA 2: ROTEAMENTO ===========
        log.info("🧠 Camada 2: Roteamento", type=input_type.value)

        routing = self._route(input_type, text)
        result.target_agent = routing.get("agent")
        result.delegation_reason = routing.get("reason")
        result.required_tools = routing.get("tools", [])

        # =========== CAMADA 3: PREPARAÇÃO ===========
        log.info("🧠 Camada 3: Preparação", agent=result.target_agent)

        if result.target_agent:
            result.task_id = self._next_task_id()
            result.execution_plan = self._build_execution_plan(
                text, result.target_agent, attachments
            )
            result.response_format = "delegation"
        else:
            result.response_format = "direct"

        # =========== CAMADA 4: DECISÃO FINAL ===========
        log.info("🧠 Camada 4: Resposta", format=result.response_format)

        return result

    def _assess_urgency(self, text: str, input_type: InputType) -> Urgency:
        """Avalia urgência baseado em padrões"""
        text_lower = text.lower()
        if any(w in text_lower for w in ["urgente", "agora", "emergência", "caiu", "fora do ar"]):
            return Urgency.CRITICAL
        if any(w in text_lower for w in ["rápido", "logo", "priority"]):
            return Urgency.HIGH
        if input_type == InputType.AUTOMATION:
            return Urgency.LOW
        return Urgency.NORMAL

    async def _check_continuation(self, text: str) -> bool:
        """Verifica se é continuação de tarefa existente"""
        # TODO: checar tasks ativas no banco
        return False

    def _route(self, input_type: InputType, text: str) -> dict:
        """Roteamento baseado em tipo e conteúdo"""
        routing_map = {
            InputType.IMAGE: {"agent": "vision", "reason": "Análise de imagem", "tools": []},
            InputType.AUDIO: {"agent": "transcriber", "reason": "Transcrição de áudio", "tools": ["ffmpeg"]},
            InputType.VIDEO: {"agent": "vision", "reason": "Análise de vídeo", "tools": []},
            InputType.CODE: {"agent": "builder", "reason": "Tarefa de código", "tools": ["shell_exec", "file_ops"]},
            InputType.COMMAND: {"agent": None, "reason": "Comando direto", "tools": []},
            InputType.DOCUMENT: {"agent": "builder", "reason": "Análise de documento", "tools": ["file_ops"]},
        }

        if input_type in routing_map:
            return routing_map[input_type]

        # TEXT ou UNKNOWN: Core resolve diretamente
        return {"agent": None, "reason": "Resposta direta do Core", "tools": []}

    def _build_execution_plan(self, text: str, agent: str,
                               attachments: list[str] = None) -> str:
        """Monta o plano de execução para o agente"""
        plan = f"Tarefa para agent:{agent}\n"
        plan += f"Pedido: {text}\n"
        if attachments:
            plan += f"Arquivos: {', '.join(attachments)}\n"
        plan += f"Resultado esperado: resposta completa e direta"
        return plan
