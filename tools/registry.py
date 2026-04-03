"""
Open-PY — Tools Registry
Registro e controle de ferramentas disponíveis para agentes.
"""

import asyncio
import os
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

import aiohttp
import aiofiles
from duckduckgo_search import DDGS

from shared.logger import get_logger

log = get_logger("tools")


# ============================================
# MODELO DE FERRAMENTA
# ============================================

@dataclass
class Tool:
    name: str
    description: str
    function: Callable
    category: str             # io | network | system | ai | custom
    requires_network: bool = False
    requires_filesystem: bool = False
    requires_shell: bool = False
    restricted_to: Optional[list[str]] = None


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
    """Lê conteúdo de um arquivo"""
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


async def execute_command(command: str, timeout: int = 30) -> dict:
    """Executa comando shell com timeout"""
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
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": f"Timeout ({timeout}s)", "returncode": -1}


async def http_get(url: str, headers: dict = None) -> dict:
    """Faz GET HTTP"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            body = await resp.text()
            return {"status": resp.status, "body": body[:5000]}


# ============================================
# REGISTRY
# ============================================

class ToolRegistry:
    """Registry global de ferramentas"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._register_builtins()

    def _register_builtins(self):
        """Registra todas as ferramentas builtin"""
        builtins = [
            Tool("web_search", "Busca na web via DuckDuckGo", web_search,
                 "network", requires_network=True),
            Tool("read_file", "Lê conteúdo de arquivo", read_file,
                 "io", requires_filesystem=True),
            Tool("write_file", "Escreve conteúdo em arquivo", write_file,
                 "io", requires_filesystem=True),
            Tool("list_files", "Lista arquivos de diretório", list_files,
                 "io", requires_filesystem=True),
            Tool("delete_file", "Deleta arquivo", delete_file,
                 "io", requires_filesystem=True),
            Tool("shell_exec", "Executa comando shell", execute_command,
                 "system", requires_shell=True),
            Tool("http_get", "Faz GET HTTP", http_get,
                 "network", requires_network=True),
        ]
        for tool in builtins:
            self._tools[tool.name] = tool

        log.info(f"✅ {len(builtins)} ferramentas builtin registradas")

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

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

    def list_all(self) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "category": t.category} for t in self._tools.values()]
