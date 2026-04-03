"""
Open-PY — Agent Factory
Cria agentes dinamicamente: builtin ou customizados.
"""

from shared.models import AgentConfig
from shared.config import OpenPYConfig
from shared.logger import get_logger
from agents.base import AgentBase
from agents.registry import AgentRegistry

log = get_logger("factory")


# ============================================
# DEFINIÇÕES DOS AGENTES BUILTIN
# ============================================

BUILTIN_AGENTS = {
    "vision": AgentConfig(
        agent_id="vision",
        name="vision",
        description="Analisa imagens, screenshots e vídeos",
        agent_type="builtin",
        system_prompt="""Você é o VISION, agente de análise visual do Open-PY.
Sua função: analisar imagens e vídeos, extrair texto (OCR), descrever conteúdo,
identificar elementos visuais. Responda em português brasileiro, direto e objetivo.
Se receber uma descrição de imagem, analise detalhadamente.""",
        allowed_tools=[],
        can_access_network=False,
        can_write_files=False,
    ),

    "builder": AgentConfig(
        agent_id="builder",
        name="builder",
        description="Cria código, scripts, debug, refatoração",
        agent_type="builtin",
        system_prompt="""Você é o BUILDER, agente de desenvolvimento do Open-PY.
Sua função: escrever código, debugar, refatorar, criar scripts e resolver problemas técnicos.
Linguagens: Python, JavaScript, Node.js, Bash, SQL, HTML/CSS.
Regras: código limpo, com tratamento de erros, comentários quando necessário.
Responda em português brasileiro.""",
        allowed_tools=["shell_exec", "file_ops", "http_client"],
        can_exec_commands=True,
        can_write_files=True,
        can_access_network=True,
        sandbox_network=True,
    ),

    "cleaner": AgentConfig(
        agent_id="cleaner",
        name="cleaner",
        description="Limpeza segura de arquivos e resíduos",
        agent_type="builtin",
        system_prompt="""Você é o CLEANER, agente de limpeza do Open-PY.
Sua função: limpar arquivos temporários, logs antigos, resíduos de agentes deletados.
REGRA ABSOLUTA: NUNCA delete arquivos fora das pastas autorizadas.
Pastas autorizadas: /opt/open-py/data/media/, /opt/open-py/data/agents/, /tmp/open-py/
Responda em português brasileiro.""",
        allowed_tools=["file_ops"],
        can_write_files=True,
        can_exec_commands=False,
        allowed_paths=["/opt/open-py/data/media/", "/opt/open-py/data/agents/", "/tmp/open-py/"],
    ),

    "researcher": AgentConfig(
        agent_id="researcher",
        name="researcher",
        description="Pesquisa profunda na web e análise",
        agent_type="builtin",
        system_prompt="""Você é o RESEARCHER, agente de pesquisa do Open-PY.
Sua função: fazer pesquisas na web, analisar resultados, sintetizar informações.
Use a ferramenta web_search para buscar. Cite fontes quando possível.
Responda em português brasileiro, de forma organizada e detalhada.""",
        allowed_tools=["web_search", "http_client"],
        can_access_network=True,
        can_write_files=False,
        sandbox_network=True,
    ),

    "transcriber": AgentConfig(
        agent_id="transcriber",
        name="transcriber",
        description="Transcreve áudios e vídeos para texto",
        agent_type="builtin",
        system_prompt="""Você é o TRANSCRIBER, agente de transcrição do Open-PY.
Sua função: transcrever áudios recebidos para texto.
Se receber uma transcrição, formate-a de forma limpa e legível.
Responda em português brasileiro.""",
        allowed_tools=["file_ops"],
        can_write_files=True,
        can_exec_commands=True,  # Para rodar ffmpeg/whisper
    ),

    "agent_creator": AgentConfig(
        agent_id="agent_creator",
        name="agent_creator",
        description="Meta-agente que cria specs de novos agentes",
        agent_type="builtin",
        system_prompt="""Você é o AGENT CREATOR do Open-PY.
Sua ÚNICA função: criar specs JSON de novos agentes quando o Core pedir.

Retorne APENAS um JSON válido com esta estrutura:
{
    "name": "nome_do_agente",
    "description": "O que ele faz",
    "type": "temporary",
    "model": "default",
    "tools": [],
    "permissions": {
        "network": false,
        "write_files": false,
        "exec_commands": false,
        "read_memory": false
    },
    "system_prompt": "Prompt completo e autossuficiente para o agente"
}

REGRAS:
- Mínimo privilégio: só dê permissões NECESSÁRIAS
- Temporário por padrão
- System prompt deve ser COMPLETO (agente não tem histórico)""",
        allowed_tools=[],
        can_access_network=False,
        can_write_files=False,
    ),
}


class AgentFactory:
    """Fábrica de agentes"""

    def __init__(self, registry: AgentRegistry, config: OpenPYConfig,
                 llm_router=None):
        self.registry = registry
        self.config = config
        self.llm = llm_router

    async def create_builtin(self, name: str) -> AgentBase:
        """Cria e registra um agente builtin"""
        if name not in BUILTIN_AGENTS:
            raise ValueError(f"Agente builtin '{name}' não existe")

        agent_config = BUILTIN_AGENTS[name].model_copy()
        agent = AgentBase(config=agent_config, llm_router=self.llm)
        self.registry.register(agent)
        log.info("✅ Agente builtin criado", name=name)
        return agent

    async def create_custom(self, spec: dict) -> AgentBase:
        """Cria agente customizado a partir de spec"""
        agent_config = AgentConfig(
            name=spec.get("name", "custom"),
            description=spec.get("description", ""),
            agent_type=spec.get("type", "temporary"),
            model=spec.get("model", "default"),
            system_prompt=spec.get("system_prompt", ""),
            allowed_tools=spec.get("tools", []),
            can_access_network=spec.get("permissions", {}).get("network", False),
            can_write_files=spec.get("permissions", {}).get("write_files", False),
            can_exec_commands=spec.get("permissions", {}).get("exec_commands", False),
            can_read_memory=spec.get("permissions", {}).get("read_memory", False),
        )

        agent = AgentBase(config=agent_config, llm_router=self.llm)
        self.registry.register(agent)
        log.info("✅ Agente customizado criado", name=agent_config.name)
        return agent

    async def create_all_builtins(self):
        """Cria todos os agentes builtin"""
        for name in BUILTIN_AGENTS:
            if not self.registry.get(name):
                await self.create_builtin(name)
        log.info(f"✅ {len(BUILTIN_AGENTS)} agentes builtin criados")

    async def destroy_agent(self, agent_id: str):
        """Destrói agente com zero resíduo"""
        agent = self.registry.get(agent_id)
        if agent:
            await agent.stop()
            self.registry.unregister(agent_id)
            log.info("🗑️ Agente destruído — zero resíduo", agent=agent_id)
