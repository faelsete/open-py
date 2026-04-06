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
    version: str = "4.1.0"
    language: str = "pt-BR"
    default_model: str = ""
    fallback_model: str = ""
    max_concurrent_agents: int = 10
    thinking_layers: int = 4
    install_dir: str = "/opt/open-py"
    log_level: str = "DEBUG"  # DEBUG, INFO, WARNING, ERROR


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
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    min_ram_gb: int = 4      # RAM mínima para auto-enable
    request_timeout: int = 10  # Timeout em segundos para API call

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
    """Configuração do túnel de execução v4.1"""
    enabled: bool = True
    # Gates individuais (todos ON por padrão)
    gate_memory_recall: bool = True
    gate_validate: bool = True
    gate_think: bool = True        # v4.1: Raciocínio neural
    # Circuit breaker
    max_gate_failures: int = 3
    gate_cooldown_minutes: int = 5
    # Timeouts por gate (segundos)
    gate_timeout_capture: int = 5
    gate_timeout_memory: int = 10
    gate_timeout_route: int = 5
    gate_timeout_think: int = 30   # v4.1: Tempo para raciocinar
    gate_timeout_prepare: int = 5
    gate_timeout_execute: int = 300
    gate_timeout_validate: int = 15


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
    model: str = ""  # Modelo específico deste provedor (sem prefixo LiteLLM)


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
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
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
