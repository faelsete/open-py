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
        model="nvidia/qwen/qwen2.5-vl-72b-instruct",  # v3.0: Modelo de visão dedicado
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
        description="Cria código, scripts, debug, refatoração, PDFs, planilhas",
        agent_type="builtin",
        model="nvidia/qwen/qwen3.5-coder-32b-instruct",
        system_prompt="""Você é o BUILDER, agente de desenvolvimento do Open-PY.
Sua função: escrever código, debugar, refatorar, criar scripts e resolver problemas técnicos.
Linguagens: Python, JavaScript, Node.js, Bash, SQL, HTML/CSS.

VOCÊ TEM FERRAMENTAS. USE-AS OBRIGATORIAMENTE:
- shell_exec: para executar comandos no terminal
- write_file/read_file: para criar e ler arquivos
- python_exec: para testar código Python
- create_pdf/create_csv/create_xlsx: para gerar documentos
- download_file: para baixar arquivos da internet
- pip_install: para instalar pacotes Python

NUNCA apenas sugira comandos. EXECUTE-OS usando as ferramentas.
Regras: código limpo, tratamento de erros, comentários quando necessário.
Responda em português brasileiro.""",
        allowed_tools=["shell_exec", "read_file", "write_file", "list_files",
                       "delete_file", "http_get", "python_exec",
                       "create_pdf", "create_csv", "create_xlsx", "read_pdf",
                       "download_file", "pip_install", "system_info",
                       "move_file", "copy_file", "find_files"],
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

USE as ferramentas para executar a limpeza de verdade:
- list_files: para ver o que existe
- delete_file: para remover arquivos
- find_files: para buscar por padrão
- move_file: para reorganizar

REGRA ABSOLUTA: NUNCA delete arquivos fora das pastas autorizadas.
Pastas autorizadas: /opt/open-py/data/media/, /opt/open-py/data/agents/, /tmp/open-py/
Responda em português brasileiro.""",
        allowed_tools=["list_files", "delete_file", "find_files", "move_file",
                       "read_file", "copy_file"],
        can_write_files=True,
        can_exec_commands=False,
        allowed_paths=["/opt/open-py/data/media/", "/opt/open-py/data/agents/", "/tmp/open-py/"],
    ),

    "researcher": AgentConfig(
        agent_id="researcher",
        name="researcher",
        description="Pesquisa profunda na web, navegação e análise",
        agent_type="builtin",
        model="nvidia/kimi-k2.5",
        system_prompt="""Você é o RESEARCHER, agente de pesquisa do Open-PY.
Sua função: fazer pesquisas na web, analisar resultados, sintetizar informações.

VOCÊ TEM FERRAMENTAS. USE-AS OBRIGATORIAMENTE:
- web_search: busca rápida via DuckDuckGo
- browser_navigate: abre URLs para ler conteúdo completo
- browser_get_text: extrai texto de páginas
- browser_screenshot: captura visual de páginas
- http_get: requisições HTTP diretas

FLUXO: web_search → encontrar URLs → browser_navigate → browser_get_text → sintetizar
Cite fontes com URLs. Responda em português brasileiro.""",
        allowed_tools=["web_search", "http_get", "browser_navigate",
                       "browser_get_text", "browser_screenshot",
                       "browser_click", "browser_type", "browser_wait",
                       "browser_close"],
        can_access_network=True,
        can_write_files=True,
        sandbox_network=True,
    ),

    "transcriber": AgentConfig(
        agent_id="transcriber",
        name="transcriber",
        description="Transcreve áudios e vídeos para texto",
        agent_type="builtin",
        system_prompt="""Você é o TRANSCRIBER, agente de transcrição do Open-PY.
Sua função: transcrever áudios recebidos para texto.

USE as ferramentas:
- shell_exec: para rodar ffmpeg e whisper
- read_file: para ler transcrições geradas
- write_file: para salvar transcrições

FLUXO OBRIGATÓRIO para áudios:
1. shell_exec('ffmpeg -i input.ogg -ar 16000 -ac 1 output.wav')
2. shell_exec('whisper output.wav --language pt --model small')
3. read_file para pegar o resultado
4. Formatar e retornar texto limpo

Responda em português brasileiro.""",
        allowed_tools=["shell_exec", "read_file", "write_file", "list_files"],
        can_write_files=True,
        can_exec_commands=True,
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
                 llm_router=None, tool_registry=None):
        self.registry = registry
        self.config = config
        self.llm = llm_router
        self.tool_registry = tool_registry  # v4.0

    async def create_builtin(self, name: str) -> AgentBase:
        """Cria e registra um agente builtin"""
        if name not in BUILTIN_AGENTS:
            raise ValueError(f"Agente builtin '{name}' não existe")

        agent_config = BUILTIN_AGENTS[name].model_copy()
        agent = AgentBase(config=agent_config, llm_router=self.llm,
                          tool_registry=self.tool_registry)  # v4.0
        self.registry.register(agent)
        log.info("✅ Agente builtin criado", name=name,
                 tools=len(agent_config.allowed_tools))
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

        agent = AgentBase(config=agent_config, llm_router=self.llm,
                          tool_registry=self.tool_registry)  # v4.0
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
