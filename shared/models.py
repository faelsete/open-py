"""
Open-PY — Modelos de Dados Globais
Pydantic models compartilhados entre todos os módulos.
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
