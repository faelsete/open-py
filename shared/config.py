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
    version: str = "1.0.0"
    language: str = "pt-BR"
    default_model: str = ""
    fallback_model: str = ""
    max_concurrent_agents: int = 10
    thinking_layers: int = 4
    install_dir: str = "/opt/open-py"


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
