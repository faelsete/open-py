"""
Open-PY — Agent Registry
Mantém registro de todos os agentes ativos no sistema.
"""

from typing import Optional
from shared.models import AgentConfig
from shared.logger import get_logger
from agents.base import AgentBase

log = get_logger("registry")


class AgentRegistry:
    """Registry central de agentes ativos"""

    def __init__(self):
        self._agents: dict[str, AgentBase] = {}

    def register(self, agent: AgentBase):
        """Registra um agente"""
        self._agents[agent.agent_id] = agent
        # Também registra por nome para acesso rápido
        self._agents[agent.name] = agent
        log.info("🤖 Agente registrado", name=agent.name, id=agent.agent_id)

    def unregister(self, agent_id: str):
        """Remove um agente do registry"""
        agent = self._agents.pop(agent_id, None)
        if agent:
            self._agents.pop(agent.name, None)
            log.info("🗑️ Agente desregistrado", name=agent.name)

    def get(self, identifier: str) -> Optional[AgentBase]:
        """Busca agente por ID ou nome"""
        return self._agents.get(identifier)

    def list_all(self) -> list[dict]:
        """Lista todos os agentes únicos"""
        seen = set()
        result = []
        for agent in self._agents.values():
            if agent.agent_id not in seen:
                seen.add(agent.agent_id)
                result.append(agent.to_dict())
        return result

    async def stop_all(self):
        """Para todos os agentes"""
        seen = set()
        for agent in self._agents.values():
            if agent.agent_id not in seen:
                seen.add(agent.agent_id)
                await agent.stop()
        log.info("✅ Todos agentes parados")
