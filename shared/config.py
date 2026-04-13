"""
Open-PY — Configuração Global
Carrega e valida openpy.toml usando Pydantic.
"""

import os
import tomli
import tomli_w
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional


# ============================================
# MODELOS DE CONFIGURAÇÃO
# ============================================

class CoreConfig(BaseModel):
    name: str = "Open-PY"
    version: str = "5.1.0"
    language: str = "pt-BR"
    default_model: str = ""
    fallback_model: str = ""
    max_concurrent_agents: int = 10
    thinking_layers: int = 4
    install_dir: str = "/opt/open-py"
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "openpy"
    user: str = "openpy"
    password: str = ""

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class TelegramConfig(BaseModel):
    bot_token: str = ""
    allowed_users: list[int] = Field(default_factory=list)
    max_message_length: int = 4096
    polling_mode: bool = True


class MemoryConfig(BaseModel):
    context_max_tokens: int = 128000
    context_save_interval_minutes: int = 60
    migration_hour: int = 0
    migration_minute: int = 0
    discard_md_after_migration: bool = True
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    max_search_results: int = 10
    # v3.0: Smart compaction
    compact_threshold_pct: float = 0.80    # Compactar em 80% da window
    compact_light_pct: float = 0.60        # Compactação leve em 60%
    compact_light_min_entries: int = 15    # Mínimo de entradas para compactação leve
    # v3.0: Background extraction
    extraction_min_tokens: int = 3000      # Min tokens acumulados para extração
    extraction_min_interactions: int = 10  # Min interações entre extrações


class OllamaConfig(BaseModel):
    """Configuração do Ollama para embeddings locais (GPU-accelerated)"""
    enabled: str = "auto"    # "auto" | "on" | "off"
    url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"        # Padrão do instalador
    embedding_dimensions: int = 1024
    min_ram_gb: int = 4      # RAM mínima para auto-enable
    request_timeout: int = 15  # Timeout em segundos para API call

    def should_enable(self) -> bool:
        """Auto-detect: ON se RAM >= min_ram_gb, OFF caso contrário"""
        if self.enabled == "on":
            return True
        if self.enabled == "off":
            return False
        # Auto-detect
        try:
            import psutil
            total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
            return total_ram_gb >= self.min_ram_gb
        except Exception:
            return False


class PipelineConfig(BaseModel):
    """[DEPRECATED v5.0] Configuração do túnel de execução v4.1 — mantida para backward compat."""
    enabled: bool = False  # v5.0: Desabilitado, substituído pelo Cortex
    gate_memory_recall: bool = True
    gate_validate: bool = False
    gate_think: bool = False
    max_gate_failures: int = 3
    gate_cooldown_minutes: int = 5
    gate_timeout_capture: int = 5
    gate_timeout_memory: int = 30
    gate_timeout_route: int = 5
    gate_timeout_think: int = 60
    gate_timeout_prepare: int = 5
    gate_timeout_execute: int = 180
    gate_timeout_validate: int = 30


class CortexConfig(BaseModel):
    """v5.0: Configuração do Cortex (core unificado com thinking adaptativo)."""
    enabled: bool = True
    # Tokens máximos por depth level
    depth_0_max_tokens: int = 200
    depth_1_max_tokens: int = 1024
    depth_2_max_tokens: int = 4096
    depth_3_max_tokens: int = 8192
    # Modelos por depth (vazio = usa default_model da config core)
    depth_0_model: str = ""   # Modelo mais barato para saudações
    depth_3_model: str = ""   # Modelo melhor para tarefas complexas
    # Agentic loop
    max_tool_iterations: int = 15
    tool_timeout_seconds: int = 60
    # Core memory limits
    core_memory_persona_chars: int = 1000
    core_memory_user_chars: int = 2000
    core_memory_directives_chars: int = 1500


class SkillStoreConfig(BaseModel):
    """v5.0: Configuração do banco de habilidades aprendidas."""
    enabled: bool = True
    min_success_to_reuse: int = 2         # Usa skill após N sucessos
    similarity_threshold: float = 0.85     # Threshold para considerar tarefa similar
    max_skills: int = 500                  # Limite de skills no banco
    cleanup_days: int = 7                  # Limpa skills com 0 sucessos após N dias
    max_skill_age_days: int = 90           # Idade máxima sem uso antes de purge


class VoiceConfig(BaseModel):
    """v5.1: Configuração de voz (STT + TTS)."""
    # STT (Speech-to-Text) — faster-whisper
    stt_enabled: bool = True
    stt_model: str = "base"        # tiny, base, small, medium, large-v3
    stt_device: str = "auto"       # auto, cpu, cuda
    stt_compute: str = "auto"      # auto, int8, float16
    # TTS (Text-to-Speech) — piper-tts
    tts_enabled: bool = True
    tts_language: str = "pt-BR"    # pt-BR, en-US, es-ES
    tts_auto_reply: bool = False   # Responder com audio quando user manda audio
    tts_max_chars: int = 2000      # Máximo de caracteres por síntese


class ValidatorConfig(BaseModel):
    """Configuração do quality gate"""
    enabled: bool = True
    model: str = ""  # Vazio = usa o modelo ativo do router (mais barato)
    # Skip para respostas curtas (confirmações, emojis, etc)
    min_response_length: int = 100
    # Máximo de re-tentativas se resposta for rejeitada
    max_retries: int = 1
    # Score mínimo de confiança para aprovar
    min_confidence: float = 0.7


class ProviderConfig(BaseModel):
    api_key: str = ""
    api_base: str = ""
    enabled: bool = False
    model: str = ""  # Modelo ativo (sem prefixo LiteLLM)
    models: list[str] = Field(default_factory=list)  # Pool de modelos disponíveis + fallback


class ProvidersConfig(BaseModel):
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    nvidia: ProviderConfig = Field(default_factory=ProviderConfig)
    opencode: ProviderConfig = Field(default_factory=ProviderConfig)


class SchedulerConfig(BaseModel):
    heartbeat_interval_seconds: int = 60
    max_cron_jobs: int = 50


class DoctorConfig(BaseModel):
    auto_repair: bool = True
    snapshot_on_startup: bool = True


class OpenPYConfig(BaseModel):
    core: CoreConfig = Field(default_factory=CoreConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)  # deprecated v5.0
    cortex: CortexConfig = Field(default_factory=CortexConfig)        # v5.0: substitui pipeline
    skill_store: SkillStoreConfig = Field(default_factory=SkillStoreConfig)  # v5.0
    voice: VoiceConfig = Field(default_factory=VoiceConfig)                  # v5.1: STT + TTS
    validator: ValidatorConfig = Field(default_factory=ValidatorConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    doctor: DoctorConfig = Field(default_factory=DoctorConfig)


# ============================================
# CARREGAMENTO
# ============================================

_config: Optional[OpenPYConfig] = None


def get_config_path() -> Path:
    """Retorna o caminho do openpy.toml"""
    install_dir = os.environ.get("OPENPY_DIR", "/opt/open-py")
    return Path(install_dir) / "openpy.toml"


def load_config(path: Optional[Path] = None) -> OpenPYConfig:
    """Carrega e valida a configuração"""
    global _config

    if _config is not None:
        return _config

    config_path = path or get_config_path()

    if not config_path.exists():
        _config = OpenPYConfig()
        return _config

    with open(config_path, "rb") as f:
        raw = tomli.load(f)

    _config = OpenPYConfig(**raw)
    return _config


def save_config(config: OpenPYConfig, path: Optional[Path] = None):
    """Salva a configuração no openpy.toml"""
    config_path = path or get_config_path()
    data = config.model_dump()

    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)


def get_config() -> OpenPYConfig:
    """Retorna a configuração já carregada"""
    global _config
    if _config is None:
        return load_config()
    return _config
