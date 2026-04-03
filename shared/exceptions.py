"""
Open-PY — Exceções Customizadas
Hierarquia de erros para tratamento preciso.
"""


class OpenPYError(Exception):
    """Erro base do Open-PY"""
    pass


# ============================================
# CORE
# ============================================

class CoreError(OpenPYError):
    """Erro no Core Agent"""
    pass


class ThinkingError(CoreError):
    """Erro no Thinking Engine"""
    pass


class RoutingError(CoreError):
    """Erro no roteamento de mensagens"""
    pass


# ============================================
# AGENTES
# ============================================

class AgentError(OpenPYError):
    """Erro genérico de agente"""
    pass


class AgentNotFoundError(AgentError):
    """Agente não encontrado no registry"""
    pass


class AgentTimeoutError(AgentError):
    """Agente excedeu o timeout"""
    pass


class AgentCreationError(AgentError):
    """Falha ao criar agente"""
    pass


class SandboxError(AgentError):
    """Erro no sandbox/isolamento do agente"""
    pass


# ============================================
# MEMÓRIA
# ============================================

class MemoryError(OpenPYError):
    """Erro no sistema de memória"""
    pass


class MemorySearchError(MemoryError):
    """Erro na busca de memórias"""
    pass


class MigrationError(MemoryError):
    """Erro na migração de memórias para PostgreSQL"""
    pass


# ============================================
# TELEGRAM
# ============================================

class TelegramError(OpenPYError):
    """Erro na integração Telegram"""
    pass


class UnauthorizedError(TelegramError):
    """Usuário não autorizado"""
    pass


# ============================================
# PROVEDORES
# ============================================

class ProviderError(OpenPYError):
    """Erro no provedor LLM"""
    pass


class NoProviderAvailableError(ProviderError):
    """Nenhum provedor LLM configurado ou disponível"""
    pass


class APIKeyError(ProviderError):
    """Chave API inválida ou ausente"""
    pass


# ============================================
# DOCTOR
# ============================================

class DoctorError(OpenPYError):
    """Erro no sistema de diagnóstico"""
    pass


class RepairError(DoctorError):
    """Falha no auto-reparo"""
    pass
