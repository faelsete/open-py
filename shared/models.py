"""
Open-PY — Modelos de Dados Globais
Pydantic models compartilhados entre todos os módulos.
v5.0: + DepthLevel, CoreMemoryBlock, Skill, CortexResult
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


# ============================================
# ENUMS
# ============================================

class InputType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    CODE = "code"
    COMMAND = "command"
    AUTOMATION = "automation"
    UNKNOWN = "unknown"


class DepthLevel(int, Enum):
    """Profundidade de raciocínio — define modelo, tokens, contexto."""
    SHALLOW = 0     # Saudações, confirmações → resposta instantânea
    LIGHT = 1       # Perguntas simples, conversa casual
    STANDARD = 2    # Tarefas com tools, código, pesquisa
    DEEP = 3        # Arquitetura, multi-step, debugging complexo


class Urgency(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def timeout(self) -> int:
        return {"critical": 10, "high": 30, "normal": 120, "low": 600}[self.value]


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    ERROR = "error"
    STOPPED = "stopped"
    TERMINATED = "terminated"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MemoryType(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    ERROR = "error"
    PROJECT = "project"
    INTERACTION = "interaction"
    SKILL = "skill"
    FEEDBACK = "feedback"


# ============================================
# MODELOS — THINKING ENGINE
# ============================================

class ThinkingResult(BaseModel):
    """Resultado do raciocínio em 4 camadas"""
    # Camada 1 — Captura
    raw_input: str = ""
    input_type: InputType = InputType.UNKNOWN
    urgency: Urgency = Urgency.NORMAL
    is_continuation: bool = False
    related_task_id: Optional[str] = None

    # Camada 2 — Roteamento
    target_agent: Optional[str] = None
    delegation_reason: Optional[str] = None
    required_tools: list[str] = Field(default_factory=list)
    required_context: dict[str, Any] = Field(default_factory=dict)

    # Camada 3 — Execução
    task_id: Optional[str] = None
    execution_plan: Optional[str] = None

    # Camada 4 — Resposta
    response_format: str = "direct"
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================
# MODELOS — AGENTES
# ============================================

class AgentConfig(BaseModel):
    """Configuração de um agente"""
    agent_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    description: str = ""
    agent_type: str = "temporary"

    # LLM
    model: str = "default"
    system_prompt: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7

    # Permissões
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    can_read_memory: bool = False
    can_write_files: bool = False
    can_exec_commands: bool = False
    can_access_network: bool = False
    allowed_paths: list[str] = Field(default_factory=list)

    # Recursos
    max_memory_mb: int = 256
    timeout_seconds: int = 300
    max_retries: int = 2

    # Sandbox
    use_sandbox: bool = True
    sandbox_network: bool = False


class AgentTask(BaseModel):
    """Tarefa enviada para um agente"""
    task_id: str = Field(default_factory=lambda: f"TASK-{uuid.uuid4().hex[:6].upper()}")
    task: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    attachments: list[str] = Field(default_factory=list)
    timeout: int = 300
    created_at: datetime = Field(default_factory=datetime.now)


class AgentResult(BaseModel):
    """Resultado de uma tarefa de agente"""
    task_id: str = ""
    status: TaskStatus = TaskStatus.COMPLETED
    output: str = ""
    artifacts: list[str] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0


# ============================================
# MODELOS — MEMÓRIA
# ============================================

class Memory(BaseModel):
    """Uma memória no sistema"""
    id: Optional[int] = None
    content: str = ""
    content_type: MemoryType = MemoryType.FACT
    source: str = "core"
    tags: list[str] = Field(default_factory=list)
    importance: int = 5
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class DailyCompilation(BaseModel):
    """Compilação diária de memórias"""
    date: str = ""
    summary: str = ""
    memory_count: int = 0
    tags: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_tasks: list[str] = Field(default_factory=list)


# ============================================
# MODELOS — IPC
# ============================================

class IPCMessage(BaseModel):
    """Mensagem IPC entre Core e Agentes"""
    method: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])


class IPCResponse(BaseModel):
    """Resposta IPC do Agente"""
    result: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    id: str = ""


# ============================================
# MODELOS — PIPELINE v3.0
# ============================================

class GateResult(BaseModel):
    """Resultado de um gate individual do pipeline"""
    gate_name: str = ""
    passed: bool = True
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    skipped: bool = False
    skip_reason: Optional[str] = None


class PipelineResult(BaseModel):
    """Resultado completo do pipeline de 6 gates"""
    success: bool = True
    response: str = ""
    failed_gate: Optional[str] = None
    error: Optional[str] = None
    gates: dict[str, GateResult] = Field(default_factory=dict)
    total_duration_ms: float = 0.0
    task_id: Optional[str] = None
    delegated_to: Optional[str] = None
    memories_extracted: int = 0


class ValidatorVerdict(BaseModel):
    """Resultado do quality gate"""
    approved: bool = True
    confidence: float = 1.0
    issues: list[str] = Field(default_factory=list)
    suggestion: Optional[str] = None
    check_type: str = "auto"  # auto | security | factual | relevance


class ExtractionResult(BaseModel):
    """Resultado de extração de memórias em background"""
    extracted: int = 0
    memories: list[dict[str, Any]] = Field(default_factory=list)
    tokens_processed: int = 0
    duration_ms: float = 0.0


class CircuitBreakerState(BaseModel):
    """Estado do circuit breaker para qualquer subsistema"""
    name: str = ""
    consecutive_failures: int = 0
    max_failures: int = 3
    last_failure: Optional[datetime] = None
    tripped: bool = False
    cooldown_minutes: int = 5

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure = datetime.now()
        if self.consecutive_failures >= self.max_failures:
            self.tripped = True

    def record_success(self):
        self.consecutive_failures = 0
        self.tripped = False

    def check(self) -> bool:
        """True = pode prosseguir. False = bloqueado."""
        if not self.tripped:
            return True
        if self.last_failure:
            from datetime import timedelta
            elapsed = datetime.now() - self.last_failure
            if elapsed > timedelta(minutes=self.cooldown_minutes):
                self.tripped = False
                self.consecutive_failures = 0
                return True
        return False


# ============================================
# MODELOS v5.0 — CORTEX
# ============================================

class CoreMemoryBlock(BaseModel):
    """Bloco editável de core memory (in-context, Letta-style).
    O agente pode ler e atualizar esses blocos via tool calls.
    """
    name: str = ""
    content: str = ""
    max_chars: int = 2000
    last_updated: datetime = Field(default_factory=datetime.now)

    def update(self, new_content: str) -> bool:
        """Atualiza conteúdo respeitando limite de caracteres."""
        if len(new_content) > self.max_chars:
            return False
        self.content = new_content
        self.last_updated = datetime.now()
        return True

    def to_prompt(self) -> str:
        """Renderiza para inclusão no system prompt."""
        if not self.content:
            return ""
        return f"<{self.name}>\n{self.content}\n</{self.name}>"


class Skill(BaseModel):
    """Habilidade aprendida pelo sistema (task executada com sucesso)."""
    id: Optional[int] = None
    task_hash: str = ""
    task_description: str = ""
    steps_json: list[dict[str, Any]] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    avg_duration_seconds: float = 0.0
    last_used: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)


class CortexResult(BaseModel):
    """Resultado unificado do Cortex (substitui PipelineResult para novos fluxos)."""
    success: bool = True
    response: str = ""
    depth: int = 1
    delegated_to: Optional[str] = None
    task_id: Optional[str] = None
    tools_called: list[str] = Field(default_factory=list)
    skill_used: Optional[str] = None
    total_duration_ms: float = 0.0
    tokens_used: int = 0
    error: Optional[str] = None


# ============================================
# MODELOS v5.1 — GOALS + PROATIVIDADE
# ============================================

class GoalStatus(str, Enum):
    """Status de um objetivo autônomo."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class Goal(BaseModel):
    """Objetivo autônomo de longo prazo.
    O agente persegue esses goals proativamente via scheduler.
    """
    id: Optional[int] = None
    user_id: int = 0
    title: str = ""
    description: str = ""
    status: GoalStatus = GoalStatus.ACTIVE
    priority: int = 5  # 1-10
    progress_pct: float = 0.0
    last_action: str = ""
    next_step: str = ""
    max_daily_actions: int = 3
    actions_today: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

