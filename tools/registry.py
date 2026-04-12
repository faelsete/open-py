"""
Open-PY v5.0 — Tools Registry
Registro, controle e execução segura de ferramentas para agentes.
Inclui: builtin tools, permission enforcement, schema generation.
v5.0: Integração com BubblewrapSandbox para execute_command.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

import aiohttp
import aiofiles
from duckduckgo_search import DDGS

from shared.logger import get_logger
from tools.schemas import function_to_schema

log = get_logger("tools")


# ============================================
# MODELO DE FERRAMENTA
# ============================================

@dataclass
class Tool:
    name: str
    description: str
    function: Callable
    category: str             # io | network | system | browser | documents | code | git
    requires_network: bool = False
    requires_filesystem: bool = False
    requires_shell: bool = False
    restricted_to: Optional[list[str]] = None
    dangerous: bool = False   # v4.0: Tools perigosas requerem confirmação

    def to_schema(self) -> dict:
        """Gera OpenAI Function Calling Schema para esta tool"""
        return function_to_schema(
            func=self.function,
            name=self.name,
            description=self.description,
        )


# ============================================
# FERRAMENTAS BUILTIN
# ============================================

async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Busca na web via DuckDuckGo (gratuito, sem API key)"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return results
    except Exception as e:
        return [{"error": str(e)}]


async def read_file(path: str) -> str:
    """Lê conteúdo de um arquivo de texto"""
    async with aiofiles.open(path, 'r', encoding='utf-8') as f:
        return await f.read()


async def write_file(path: str, content: str) -> str:
    """Escreve conteúdo em um arquivo"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    async with aiofiles.open(path, 'w', encoding='utf-8') as f:
        await f.write(content)
    return f"Arquivo salvo: {path}"


async def list_files(directory: str) -> list[str]:
    """Lista arquivos de um diretório"""
    try:
        return os.listdir(directory)
    except Exception as e:
        return [f"erro: {e}"]


async def delete_file(path: str) -> str:
    """Deleta um arquivo"""
    os.remove(path)
    return f"Arquivo deletado: {path}"


# v5.0: Singleton da sandbox (inicializado sob demanda)
_sandbox_instance = None

def _get_sandbox():
    """Retorna singleton da BubblewrapSandbox."""
    global _sandbox_instance
    if _sandbox_instance is None:
        try:
            from core.sandbox import BubblewrapSandbox
            _sandbox_instance = BubblewrapSandbox()
        except Exception:
            _sandbox_instance = None
    return _sandbox_instance


async def execute_command(command: str, timeout: int = 30) -> dict:
    """Executa comando shell com timeout.
    v5.0: Usa BubblewrapSandbox se disponível (filesystem readonly, network OFF)."""
    sandbox = _get_sandbox()
    if sandbox and sandbox.available:
        result = await sandbox.execute(
            command=command,
            allowed_paths=["/opt/open-py", "/tmp"],
            network=False,
            timeout=timeout,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "sandboxed": result.sandboxed,
            "timed_out": result.timed_out,
        }

    # Fallback: execução direta (dev/Windows)
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return {
            "stdout": stdout.decode(errors='replace'),
            "stderr": stderr.decode(errors='replace'),
            "returncode": proc.returncode,
            "sandboxed": False,
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": f"Timeout ({timeout}s)", "returncode": -1, "sandboxed": False}


async def http_get(url: str, headers: dict = None) -> dict:
    """Faz GET HTTP e retorna status + body"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            body = await resp.text()
            return {"status": resp.status, "body": body[:5000]}


# ============================================
# v4.0: PERMISSION ENFORCEMENT
# ============================================

class PermissionDenied(Exception):
    """Tool chamada sem permissão"""
    pass


# ============================================
# REGISTRY
# ============================================

class ToolRegistry:
    """Registry global de ferramentas com permission enforcement"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._register_builtins()

    def _register_builtins(self):
        """Registra todas as ferramentas builtin (v4.0: 25+ tools)"""
        # === TOOLS CORE (IO, Network, System) ===
        builtins = [
            Tool("web_search", "Busca na web via DuckDuckGo", web_search,
                 "network", requires_network=True),
            Tool("read_file", "Lê conteúdo de arquivo de texto", read_file,
                 "io", requires_filesystem=True),
            Tool("write_file", "Escreve conteúdo em arquivo", write_file,
                 "io", requires_filesystem=True),
            Tool("list_files", "Lista arquivos de diretório", list_files,
                 "io", requires_filesystem=True),
            Tool("delete_file", "Deleta arquivo", delete_file,
                 "io", requires_filesystem=True, dangerous=True),
            Tool("shell_exec", "Executa comando shell", execute_command,
                 "system", requires_shell=True, dangerous=True),
            Tool("http_get", "Faz GET HTTP", http_get,
                 "network", requires_network=True),
        ]

        # === v4.0: DOCUMENT TOOLS ===
        try:
            from tools.documents import create_pdf, read_pdf, create_csv, create_xlsx
            builtins.extend([
                Tool("create_pdf", "Cria arquivo PDF com título e conteúdo", create_pdf,
                     "documents", requires_filesystem=True),
                Tool("read_pdf", "Lê e extrai texto de arquivo PDF", read_pdf,
                     "documents", requires_filesystem=True),
                Tool("create_csv", "Cria arquivo CSV a partir de dados JSON", create_csv,
                     "documents", requires_filesystem=True),
                Tool("create_xlsx", "Cria arquivo Excel XLSX a partir de dados JSON", create_xlsx,
                     "documents", requires_filesystem=True),
            ])
        except ImportError as e:
            log.warning(f"⚠️ Document tools indisponíveis: {e}")

        # === v4.0: BROWSER TOOLS ===
        try:
            from tools.browser import (browser_navigate, browser_click, browser_type,
                                       browser_screenshot, browser_get_text,
                                       browser_execute_js, browser_wait, browser_close)
            builtins.extend([
                Tool("browser_navigate", "Navega para uma URL no navegador", browser_navigate,
                     "browser", requires_network=True),
                Tool("browser_click", "Clica em elemento por CSS selector", browser_click,
                     "browser", requires_network=True),
                Tool("browser_type", "Digita texto em campo de input", browser_type,
                     "browser", requires_network=True),
                Tool("browser_screenshot", "Captura screenshot da página", browser_screenshot,
                     "browser", requires_network=True, requires_filesystem=True),
                Tool("browser_get_text", "Extrai texto visível de elemento", browser_get_text,
                     "browser", requires_network=True),
                Tool("browser_execute_js", "Executa JavaScript na página", browser_execute_js,
                     "browser", requires_network=True, dangerous=True),
                Tool("browser_wait", "Aguarda elemento aparecer na página", browser_wait,
                     "browser", requires_network=True),
                Tool("browser_close", "Fecha o navegador", browser_close,
                     "browser"),
            ])
        except ImportError as e:
            log.warning(f"⚠️ Browser tools indisponíveis: {e}")

        # === v4.0: PYTHON EXECUTOR ===
        try:
            from tools.python_exec import python_exec
            builtins.append(
                Tool("python_exec", "Executa código Python em subprocess isolado", python_exec,
                     "code", requires_shell=True, dangerous=True)
            )
        except ImportError as e:
            log.warning(f"⚠️ Python exec indisponível: {e}")

        # === v4.0: SYSTEM TOOLS ===
        try:
            from tools.system import (download_file, pip_install, system_info,
                                      move_file, copy_file, find_files)
            builtins.extend([
                Tool("download_file", "Faz download de arquivo da internet", download_file,
                     "network", requires_network=True, requires_filesystem=True),
                Tool("pip_install", "Instala pacote Python via pip", pip_install,
                     "system", requires_shell=True, dangerous=True),
                Tool("system_info", "Retorna info do sistema (RAM, CPU, disco, GPU)", system_info,
                     "system"),
                Tool("move_file", "Move ou renomeia arquivo", move_file,
                     "io", requires_filesystem=True),
                Tool("copy_file", "Copia arquivo", copy_file,
                     "io", requires_filesystem=True),
                Tool("find_files", "Busca arquivos recursivamente por padrão", find_files,
                     "io", requires_filesystem=True),
            ])
        except ImportError as e:
            log.warning(f"⚠️ System tools indisponíveis: {e}")

        for tool in builtins:
            self._tools[tool.name] = tool

        log.info(f"✅ {len(builtins)} ferramentas registradas (v4.0)")

    def register(self, tool: Tool):
        """Registra nova ferramenta"""
        self._tools[tool.name] = tool
        log.info(f"🔧 Tool registrada: {tool.name} ({tool.category})")

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_for_agent(self, agent_id: str, allowed: list[str]) -> list[Tool]:
        """Retorna ferramentas que o agente pode usar"""
        result = []
        for name in allowed:
            tool = self._tools.get(name)
            if tool:
                if tool.restricted_to is None or agent_id in tool.restricted_to:
                    result.append(tool)
        return result

    def get_schemas_for_agent(self, agent_id: str, allowed: list[str]) -> list[dict]:
        """
        v4.0: Retorna schemas OpenAI das tools permitidas para o agente.
        Usado no `tools` param da chamada LLM.
        """
        tools = self.get_for_agent(agent_id, allowed)
        return [tool.to_schema() for tool in tools]

    async def execute_safe(self, tool_name: str, agent_config, **kwargs) -> Any:
        """
        v4.0: Execução segura com permission enforcement.
        
        Verifica:
        1. Tool existe
        2. Agent tem permissão (allowed_tools)
        3. Requisitos de rede/filesystem/shell
        4. Path dentro dos limites permitidos
        
        Raises PermissionDenied se qualquer check falhar.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            raise PermissionDenied(f"Tool '{tool_name}' não existe")

        # Check 1: Tool está na lista de permitidas
        if tool_name not in agent_config.allowed_tools:
            raise PermissionDenied(
                f"Agente '{agent_config.name}' não tem permissão para '{tool_name}'"
            )

        # Check 2: Network access
        if tool.requires_network and not agent_config.can_access_network:
            raise PermissionDenied(
                f"Tool '{tool_name}' requer rede, mas agente não tem permissão"
            )

        # Check 3: Filesystem access
        if tool.requires_filesystem and not agent_config.can_write_files:
            # Leitura é permitida, mas escrita precisa de permissão
            if tool_name in ("write_file", "delete_file"):
                raise PermissionDenied(
                    f"Tool '{tool_name}' requer escrita, mas agente não tem permissão"
                )

        # Check 4: Shell access
        if tool.requires_shell and not agent_config.can_exec_commands:
            raise PermissionDenied(
                f"Tool '{tool_name}' requer shell, mas agente não tem permissão"
            )

        # Check 5: Path sandboxing
        if agent_config.allowed_paths and tool.requires_filesystem:
            target_path = kwargs.get("path") or kwargs.get("directory") or ""
            if target_path and not any(
                target_path.startswith(p) for p in agent_config.allowed_paths
            ):
                raise PermissionDenied(
                    f"Path '{target_path}' fora dos limites: {agent_config.allowed_paths}"
                )

        # Executar com timeout
        try:
            log.info(f"🔧 Executando tool: {tool_name}", agent=agent_config.name,
                     args=str(kwargs)[:200])
            
            result = await asyncio.wait_for(
                tool.function(**kwargs),
                timeout=60.0
            )

            # Serializar resultado para string (LLM recebe texto)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, indent=2, default=str)
            return str(result)

        except asyncio.TimeoutError:
            return json.dumps({"error": f"Tool '{tool_name}' timeout (60s)"})
        except PermissionDenied:
            raise
        except Exception as e:
            log.error(f"❌ Tool '{tool_name}' falhou", error=str(e))
            return json.dumps({"error": str(e)})

    def list_all(self) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "category": t.category, "dangerous": t.dangerous}
                for t in self._tools.values()]
