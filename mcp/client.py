"""
Open-PY v4.0 — MCP Client (Model Context Protocol)
Conecta a servidores MCP externos via JSON-RPC 2.0 sobre stdio.
Auto-descobre tools e integra no ToolRegistry.
"""

import asyncio
import json
import uuid
from typing import Optional, Any

from shared.logger import get_logger

log = get_logger("mcp-client")

# MCP Protocol Constants
MCP_PROTOCOL_VERSION = "2024-11-05"
JSONRPC_VERSION = "2.0"


class MCPTransport:
    """Transporte stdin/stdout para MCP servers"""

    def __init__(self, command: str, args: list[str] = None, env: dict = None):
        self.command = command
        self.args = args or []
        self.env = env
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: dict[str, asyncio.Future] = {}

    async def start(self):
        """Inicia o servidor MCP como subprocess"""
        import os
        full_env = {**os.environ, **(self.env or {})}

        self._process = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        log.info(f"🔌 MCP server iniciado: {self.command} {' '.join(self.args)}")

    async def _read_loop(self):
        """Lê respostas JSON-RPC do stdout do server"""
        try:
            while self._process and self._process.returncode is None:
                line = await self._process.stdout.readline()
                if not line:
                    break

                try:
                    msg = json.loads(line.decode().strip())
                except json.JSONDecodeError:
                    continue

                # Resposta a um request pendente
                msg_id = msg.get("id")
                if msg_id and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if not future.done():
                        if "error" in msg:
                            future.set_exception(
                                MCPError(msg["error"].get("message", "Unknown error"))
                            )
                        else:
                            future.set_result(msg.get("result"))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"MCP read loop error: {e}")

    async def request(self, method: str, params: dict = None, timeout: float = 30) -> Any:
        """Envia request JSON-RPC e aguarda resposta"""
        if not self._process or self._process.returncode is not None:
            raise MCPError("MCP server não está rodando")

        req_id = str(uuid.uuid4())[:8]
        request = {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "method": method,
        }
        if params:
            request["params"] = params

        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        data = json.dumps(request) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise MCPError(f"Timeout ({timeout}s) em {method}")

    async def stop(self):
        """Para o servidor MCP"""
        if self._reader_task:
            self._reader_task.cancel()
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
        log.info("🔌 MCP server parado")

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None


class MCPError(Exception):
    pass


class MCPClient:
    """
    Cliente MCP completo.
    Gerencia conexão, inicialização e chamadas de tool.
    """

    def __init__(self, name: str, command: str, args: list[str] = None,
                 env: dict = None):
        self.name = name
        self.transport = MCPTransport(command=command, args=args, env=env)
        self.server_info: dict = {}
        self.available_tools: list[dict] = []
        self._initialized = False

    async def connect(self):
        """Conecta e inicializa o MCP server"""
        await self.transport.start()

        # Handshake: initialize
        result = await self.transport.request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "open-py",
                "version": "4.0.0",
            }
        })

        self.server_info = result or {}
        self._initialized = True
        log.info(f"✅ MCP '{self.name}' conectado",
                 server=self.server_info.get("serverInfo", {}))

        # Notificar que estamos ready
        try:
            await self.transport.request("notifications/initialized", {})
        except Exception:
            pass  # Notificações são fire-and-forget

        # Descobrir tools disponíveis
        await self.discover_tools()

    async def discover_tools(self):
        """Descobre tools disponíveis no MCP server"""
        try:
            result = await self.transport.request("tools/list", {})
            self.available_tools = result.get("tools", []) if result else []
            log.info(f"🔧 MCP '{self.name}': {len(self.available_tools)} tools descobertas")
            for tool in self.available_tools:
                log.debug(f"  → {tool.get('name')}: {tool.get('description', '')[:60]}")
        except Exception as e:
            log.warning(f"⚠️ MCP '{self.name}' tools/list falhou: {e}")
            self.available_tools = []

    async def call_tool(self, tool_name: str, arguments: dict = None) -> str:
        """Chama uma tool do MCP server"""
        if not self._initialized:
            raise MCPError(f"MCP '{self.name}' não inicializado")

        result = await self.transport.request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })

        if not result:
            return "{}"

        # Extrair conteúdo do resultado MCP
        content = result.get("content", [])
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "resource":
                    texts.append(json.dumps(item, ensure_ascii=False))

        return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)

    async def list_resources(self) -> list[dict]:
        """Lista recursos disponíveis no MCP server"""
        try:
            result = await self.transport.request("resources/list", {})
            return result.get("resources", []) if result else []
        except Exception:
            return []

    async def disconnect(self):
        """Desconecta do MCP server"""
        await self.transport.stop()
        self._initialized = False

    @property
    def is_connected(self) -> bool:
        return self._initialized and self.transport.is_running


class MCPRegistry:
    """
    Registry de servidores MCP.
    Gerencia múltiplos MCP servers e integra suas tools no ToolRegistry.
    """

    def __init__(self, tool_registry=None):
        self.tool_registry = tool_registry
        self._clients: dict[str, MCPClient] = {}

    async def add_server(self, name: str, command: str, args: list[str] = None,
                         env: dict = None):
        """Adiciona e conecta um MCP server"""
        client = MCPClient(name=name, command=command, args=args, env=env)

        try:
            await client.connect()
            self._clients[name] = client

            # Registrar tools do MCP no ToolRegistry
            if self.tool_registry:
                self._register_mcp_tools(client)

            log.info(f"✅ MCP '{name}' registrado com {len(client.available_tools)} tools")

        except Exception as e:
            log.error(f"❌ Falha ao conectar MCP '{name}': {e}")
            await client.disconnect()

    def _register_mcp_tools(self, client: MCPClient):
        """Registra tools de um MCP server no ToolRegistry"""
        from tools.registry import Tool

        for mcp_tool in client.available_tools:
            tool_name = f"mcp_{client.name}_{mcp_tool['name']}"
            description = mcp_tool.get("description", "")

            # Criar função wrapper para esta tool
            async def _mcp_wrapper(_client=client, _name=mcp_tool["name"], **kwargs):
                return await _client.call_tool(_name, kwargs)

            # Copiar assinatura do schema MCP
            _mcp_wrapper.__doc__ = description
            _mcp_wrapper.__name__ = tool_name

            tool = Tool(
                name=tool_name,
                description=f"[MCP:{client.name}] {description}",
                function=_mcp_wrapper,
                category="mcp",
                requires_network=True,
            )
            self.tool_registry.register(tool)

    async def remove_server(self, name: str):
        """Remove e desconecta um MCP server"""
        client = self._clients.pop(name, None)
        if client:
            await client.disconnect()
            log.info(f"🔌 MCP '{name}' removido")

    async def shutdown(self):
        """Desconecta todos os MCP servers"""
        for name, client in list(self._clients.items()):
            await client.disconnect()
        self._clients.clear()

    def get_status(self) -> dict:
        """Status de todos os MCP servers"""
        return {
            name: {
                "connected": client.is_connected,
                "tools": len(client.available_tools),
                "server_info": client.server_info.get("serverInfo", {}),
            }
            for name, client in self._clients.items()
        }
