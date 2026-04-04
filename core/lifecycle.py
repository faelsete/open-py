"""
Open-PY — Lifecycle Manager
Controla startup, running e shutdown do sistema inteiro.
v2.0: Versionamento de SOUL/ESSENCE, healthcheck
"""

import asyncio
import hashlib
import shutil
import signal
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import asyncpg

from shared.config import load_config, OpenPYConfig
from shared.logger import setup_logging, get_logger
from shared.migrations import run_migrations
from core.brain import ThinkingEngine, build_core_system_prompt

log = get_logger("lifecycle")


# Máximo de trocas de mensagem (user+assistant) por usuário mantidas em RAM
MAX_CONVERSATION_TURNS = 20


class OpenPY:
    """
    Classe principal do sistema Open-PY.
    Gerencia o ciclo de vida completo: startup → running → shutdown.
    """

    def __init__(self):
        self.config: Optional[OpenPYConfig] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.brain: Optional[ThinkingEngine] = None
        self.orchestrator = None
        self.memory_manager = None
        self.agent_registry = None
        self.agent_factory = None
        self.telegram_bot = None
        self.scheduler = None
        self.llm_router = None
        self._running = False
        self._soul = ""
        self._essence = ""

        # Histórico conversacional por usuário (RAM)
        # Chave: user_id (int) → Valor: lista de {role, content}
        self._conversation_histories: dict[int, list[dict]] = {}

    # ============================================
    # STARTUP
    # ============================================

    async def startup(self):
        """Sequência completa de inicialização"""
        log.info("🧠 Open-PY iniciando...")

        # 1. Configuração
        self.config = load_config()
        setup_logging(level="INFO")
        log.info("✅ Configuração carregada")

        # 2. Carregar identidade (soul.md + essence.md)
        await self._load_identity()

        # 3. Banco de dados
        await self._init_database()

        # 4. Provedores LLM
        await self._init_providers()

        # 5. Sistema de memória
        await self._init_memory()

        # 6. Sistema de agentes
        await self._init_agents()

        # 7. Thinking Engine
        self.brain = ThinkingEngine(
            llm_router=self.llm_router,
            memory_manager=self.memory_manager,
            agent_registry=self.agent_registry,
        )
        log.info("✅ Thinking Engine pronto")

        # 8. Orchestrator (com audit log)
        from core.orchestrator import Orchestrator
        from core.audit_log import AuditLog
        self._audit_log = AuditLog(
            log_dir=str(Path(self.config.core.install_dir) / "data" / "audit")
        )
        self.orchestrator = Orchestrator(
            agent_registry=self.agent_registry,
            agent_factory=self.agent_factory,
            memory_manager=self.memory_manager,
            db_pool=self.db_pool,
            audit_log=self._audit_log,
        )
        log.info("✅ Orchestrator pronto (com audit trail)")

        # 9. Scheduler (heartbeat + cron)
        await self._init_scheduler()

        # 10. Telegram Bot
        await self._init_telegram()

        self._running = True
        log.info("🚀 Open-PY pronto e operacional!")

    # ============================================
    # RUNNING
    # ============================================

    async def run(self):
        """Loop principal — aguarda até shutdown"""
        await self.startup()

        # Registrar handlers de sinal para shutdown graceful
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                pass  # Windows não suporta add_signal_handler

        # Iniciar Telegram bot (bloqueia até shutdown)
        if self.telegram_bot:
            log.info("📱 Telegram bot iniciando polling...")
            await self.telegram_bot.start_polling()
        else:
            # Sem Telegram: modo terminal
            log.info("⌨️ Modo terminal — sem Telegram configurado")
            while self._running:
                await asyncio.sleep(1)

    # ============================================
    # SHUTDOWN
    # ============================================

    async def shutdown(self):
        """Shutdown graceful — salva tudo, para tudo, limpa tudo"""
        log.info("🛑 Open-PY encerrando...")
        self._running = False

        # 1. Salvar memórias pendentes
        if self.memory_manager:
            try:
                await self.memory_manager.flush()
                log.info("✅ Memórias salvas")
            except Exception as e:
                log.error("Erro salvando memórias", error=str(e))

        # 2. Parar agentes
        if self.agent_registry:
            try:
                await self.agent_registry.stop_all()
                log.info("✅ Agentes parados")
            except Exception as e:
                log.error("Erro parando agentes", error=str(e))

        # 3. Parar scheduler
        if self.scheduler:
            try:
                self.scheduler.shutdown()
                log.info("✅ Scheduler parado")
            except Exception as e:
                log.error("Erro no scheduler", error=str(e))

        # 4. Parar Telegram
        if self.telegram_bot:
            try:
                await self.telegram_bot.stop()
                log.info("✅ Telegram bot parado")
            except Exception as e:
                log.error("Erro no Telegram", error=str(e))

        # 5. Fechar banco de dados
        if self.db_pool:
            try:
                await self.db_pool.close()
                log.info("✅ Banco de dados fechado")
            except Exception as e:
                log.error("Erro fechando DB", error=str(e))

        log.info("👋 Open-PY encerrado com sucesso")

    # ============================================
    # PROCESS INPUT (Entry point para mensagens)
    # ============================================

    async def process(self, input_text: str, input_type: str = "unknown",
                      attachments: list[str] = None,
                      user_id: int = None, target_agent: str = None) -> dict:
        """
        Ponto de entrada principal para processar qualquer input.
        
        Fluxo:
        1. Classificar input (4 camadas do brain)
        2. Buscar memórias SEMANTICAMENTE relevantes (como um cérebro humano)
        3. Injetar APENAS o contexto necessário no prompt
        4. Delegar ou responder diretamente
        5. Salvar interação na memória
        """
        try:
            from shared.models import InputType

            # Converter tipo
            try:
                itype = InputType(input_type)
            except ValueError:
                itype = InputType.UNKNOWN

            # Pensar (4 camadas)
            thinking = await self.brain.think(
                text=input_text,
                input_type=itype,
                attachments=attachments,
            )

            # Obter histórico conversacional do usuário
            history = self._get_conversation_history(user_id)

            # Se tem agente alvo, delegar COM CONTEXTO
            if thinking.target_agent:
                result = await self.orchestrator.dispatch(
                    thinking, attachments,
                    conversation_history=history[-10:]  # Últimas 5 trocas para o agente
                )

                # Salvar no histórico conversacional
                response_text = result.output or result.error or "Sem resultado"
                self._add_to_conversation(user_id, "user", input_text)
                self._add_to_conversation(user_id, "assistant", response_text)

                # Salvar na memória de longo prazo
                if self.memory_manager:
                    await self.memory_manager.buffer_interaction(input_text, response_text)

                return {
                    "response": response_text,
                    "task_id": result.task_id,
                    "status": result.status.value,
                    "delegated_to": thinking.target_agent,
                }

            # Senão, Core responde diretamente via LLM
            if self.llm_router:
                # === MEMÓRIA SEMÂNTICA (longo prazo) ===
                semantic_context = ""
                if self.memory_manager:
                    semantic_context = await self._build_semantic_context(
                        input_text, user_id
                    )

                system_prompt = build_core_system_prompt(self._soul, self._essence)

                # Injetar contexto semântico no prompt (se houver)
                if semantic_context:
                    system_prompt += f"\n\n{semantic_context}"

                # === HISTÓRICO CONVERSACIONAL (curto prazo) ===
                # Injetar histórico entre system e user para manter contexto
                messages = [
                    {"role": "system", "content": system_prompt},
                    *history,  # Últimas N trocas de mensagem
                    {"role": "user", "content": input_text},
                ]

                response = await self.llm_router.complete(messages=messages)

                # Salvar no histórico conversacional (RAM)
                self._add_to_conversation(user_id, "user", input_text)
                self._add_to_conversation(user_id, "assistant", response)

                # Salvar na memória de longo prazo (buffer → md → PostgreSQL)
                if self.memory_manager:
                    await self.memory_manager.buffer_interaction(input_text, response)

                return {"response": response, "status": "completed"}

            return {"response": "⚠️ Nenhum provedor LLM configurado. Use /config.", "status": "error"}

        except Exception as e:
            log.error("⚠️ Erro global no processamento", error=str(e))
            return {
                "response": f"⚠️ Ocorreu um erro interno ao processar sua mensagem:\n\n`{str(e)}`",
                "status": "error"
            }

    # ============================================
    # HISTÓRICO CONVERSACIONAL (Curto Prazo — RAM)
    # ============================================

    def _get_conversation_history(self, user_id: int = None) -> list[dict]:
        """
        Retorna o histórico conversacional do usuário.
        Formato: lista de {"role": "user"|"assistant", "content": "..."}
        """
        if user_id is None:
            return []
        return self._conversation_histories.get(user_id, [])

    def _add_to_conversation(self, user_id: int, role: str, content: str):
        """
        Adiciona uma mensagem ao histórico conversacional do usuário.
        Mantém apenas as últimas MAX_CONVERSATION_TURNS trocas.
        """
        if user_id is None:
            return

        if user_id not in self._conversation_histories:
            self._conversation_histories[user_id] = []

        self._conversation_histories[user_id].append({
            "role": role,
            "content": content,
        })

        # Limitar tamanho: cada troca = 2 mensagens (user + assistant)
        max_msgs = MAX_CONVERSATION_TURNS * 2
        if len(self._conversation_histories[user_id]) > max_msgs:
            self._conversation_histories[user_id] = \
                self._conversation_histories[user_id][-max_msgs:]

    def clear_conversation(self, user_id: int):
        """Limpa o histórico conversacional de um usuário"""
        self._conversation_histories.pop(user_id, None)

    async def _build_semantic_context(self, query: str, user_id: int = None,
                                       max_tokens: int = 2000) -> str:
        """
        Busca semântica de memórias relevantes ao input atual.
        
        3 fontes (prioridade):
        1. Buffer RAM (últimas interações — mais frescas)
        2. PostgreSQL via busca híbrida (longo prazo — mais amplas)
        3. Preferências do usuário (sempre úteis)
        
        Budget máximo: ~2000 tokens (≈8000 chars)
        """
        context_parts = []
        char_budget = max_tokens * 4  # ~4 chars por token
        chars_used = 0

        try:
            # 1. BUFFER RAM — Interações muito recentes (sempre disponíveis)
            buffer_results = self.memory_manager.search_buffer(query, limit=3)
            if buffer_results:
                context_parts.append("## Memórias recentes (sessão atual)")
                for mem in buffer_results:
                    content = mem.get("content", "")
                    if len(content) > 300:
                        content = content[:300] + "..."
                    if chars_used + len(content) > char_budget:
                        break
                    chars_used += len(content)
                    context_parts.append(f"- {content}")

            # 2. PostgreSQL — Busca híbrida: keyword + semântica (pgvector)
            results = await self.memory_manager.search(
                query, mode="hybrid", limit=8
            )

            if results:
                context_parts.append("\n## Memórias de longo prazo (recuperação semântica)")
                for mem in results:
                    content = mem.get("content", "")
                    if len(content) > 300:
                        content = content[:300] + "..."
                    if chars_used + len(content) > char_budget:
                        break
                    chars_used += len(content)
                    tags = mem.get("tags", [])
                    tag_str = f" [{', '.join(tags[:3])}]" if tags else ""
                    context_parts.append(f"- {content}{tag_str}")

            # 3. Preferências do usuário (sempre úteis)
            if user_id and chars_used < char_budget * 0.7:
                prefs = await self.memory_manager.search(
                    f"PREFERÊNCIA user:{user_id}",
                    mode="keyword", limit=5
                )
                if prefs:
                    context_parts.append("\n## Preferências do usuário")
                    for pref in prefs:
                        content = pref.get("content", "")[:150]
                        if chars_used + len(content) > char_budget:
                            break
                        chars_used += len(content)
                        context_parts.append(f"- {content}")

        except Exception as e:
            log.warning("⚠️ Erro buscando memória semântica", error=str(e))

        if not context_parts:
            return ""

        return "\n".join(context_parts)

    # ============================================
    # SYSTEM STATUS
    # ============================================

    async def get_system_status(self) -> dict:
        """Retorna status completo do sistema"""
        import psutil

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        agent_count = len(self.agent_registry.list_all()) if self.agent_registry else 0
        memory_count = 0
        if self.db_pool:
            try:
                row = await self.db_pool.fetchval("SELECT COUNT(*) FROM memories")
                memory_count = row or 0
            except Exception:
                pass

        return {
            "uptime": "N/A",
            "memory_count": memory_count,
            "active_agents": agent_count,
            "total_agents": agent_count,
            "pending_tasks": len(self.orchestrator._active_tasks) if self.orchestrator else 0,
            "db_size_mb": "N/A",
            "active_crons": 0,
            "last_heartbeat": "N/A",
            "ram_used_pct": mem.percent,
            "disk_used_pct": disk.percent,
        }

    # ============================================
    # INIT HELPERS (private)
    # ============================================

    async def _load_identity(self):
        """Carrega soul.md e essence.md com versionamento automático"""
        data_dir = Path(self.config.core.install_dir) / "data"
        versions_dir = data_dir / "identity_versions"
        versions_dir.mkdir(parents=True, exist_ok=True)

        soul_path = data_dir / "soul.md"
        essence_path = data_dir / "essence.md"

        if soul_path.exists():
            self._soul = soul_path.read_text(encoding="utf-8")
            self._backup_identity(soul_path, versions_dir, "soul")
            log.info("✅ soul.md carregado")
        else:
            self._soul = "Nenhuma memória permanente registrada ainda."
            log.warning("⚠️ soul.md não encontrado")

        if essence_path.exists():
            self._essence = essence_path.read_text(encoding="utf-8")
            self._backup_identity(essence_path, versions_dir, "essence")
            log.info("✅ essence.md carregado")
        else:
            self._essence = "Você é o Open-PY, assistente autônomo. Responda em português brasileiro de forma direta e objetiva."
            log.warning("⚠️ essence.md não encontrado, usando default")

    def _backup_identity(self, file_path: Path, versions_dir: Path, name: str):
        """Faz backup versionado de soul/essence com hash de integridade"""
        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Verificar se já existe backup com mesmo hash (conteúdo idêntico)
        existing = list(versions_dir.glob(f"{name}_*_{content_hash}.md"))
        if existing:
            return  # Já tem backup com este hash, não duplicar

        backup_name = f"{name}_{timestamp}_{content_hash}.md"
        backup_path = versions_dir / backup_name
        shutil.copy2(file_path, backup_path)

        # Manter últimas 20 versões
        all_versions = sorted(versions_dir.glob(f"{name}_*.md"))
        while len(all_versions) > 20:
            oldest = all_versions.pop(0)
            oldest.unlink()

        log.info(f"📦 {name}.md backup criado",
                 version=backup_name, hash=content_hash)

    async def get_health_report(self) -> dict:
        """Retorna relatório de saúde completo do sistema"""
        report = {"status": "healthy", "components": {}}

        # Database
        if self.db_pool:
            try:
                await self.db_pool.fetchval("SELECT 1")
                report["components"]["database"] = {"status": "up"}
            except Exception as e:
                report["status"] = "degraded"
                report["components"]["database"] = {"status": "down", "error": str(e)}
        else:
            report["components"]["database"] = {"status": "not_configured"}

        # LLM
        report["components"]["llm"] = {
            "status": "up" if self.llm_router else "not_configured"
        }

        # Memory
        report["components"]["memory"] = {
            "status": "up" if self.memory_manager else "not_configured"
        }

        # Agents
        if self.orchestrator:
            report["components"]["agents"] = self.orchestrator.get_health_report()
        
        # Telegram
        report["components"]["telegram"] = {
            "status": "up" if self.telegram_bot else "not_configured"
        }

        # Identity
        report["components"]["identity"] = {
            "soul_loaded": bool(self._soul and self._soul != "Nenhuma memória permanente registrada ainda."),
            "essence_loaded": bool(self._essence),
        }

        return report

    async def _init_database(self):
        """Conecta ao PostgreSQL e executa migrations"""
        dsn = self.config.database.dsn
        try:
            self.db_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
            await run_migrations(dsn)
            log.info("✅ PostgreSQL conectado e migrations executadas")
        except Exception as e:
            log.error("❌ Erro ao conectar PostgreSQL", error=str(e))
            log.warning("⚠️ Continuando sem banco de dados")
            self.db_pool = None

    async def _init_providers(self):
        """Inicializa router de provedores LLM"""
        try:
            from providers.router import LLMRouter
            self.llm_router = LLMRouter(self.config)
            log.info("✅ Provedores LLM inicializados")
        except Exception as e:
            log.warning("⚠️ Erro nos provedores LLM", error=str(e))
            self.llm_router = None

    async def _init_memory(self):
        """Inicializa sistema de memória"""
        try:
            from memory.manager import MemoryManager
            self.memory_manager = MemoryManager(
                db_pool=self.db_pool,
                config=self.config.memory,
                install_dir=self.config.core.install_dir,
            )
            log.info("✅ Sistema de memória pronto")
        except Exception as e:
            log.warning("⚠️ Erro no sistema de memória", error=str(e))
            self.memory_manager = None

    async def _init_agents(self):
        """Inicializa registry, factory e cria agentes builtin"""
        try:
            from agents.registry import AgentRegistry
            from agents.factory import AgentFactory
            self.agent_registry = AgentRegistry()
            self.agent_factory = AgentFactory(
                registry=self.agent_registry,
                config=self.config,
                llm_router=self.llm_router,
            )

            # CRIAR TODOS OS AGENTES BUILTIN NO STARTUP
            await self.agent_factory.create_all_builtins()

            agents = self.agent_registry.list_all()
            log.info(f"✅ Sistema de agentes pronto — {len(agents)} agentes ativos")
        except Exception as e:
            log.warning("⚠️ Erro no sistema de agentes", error=str(e))

    async def _init_scheduler(self):
        """Inicializa heartbeat e cron"""
        try:
            from scheduler.manager import SchedulerManager
            self.scheduler = SchedulerManager(self)
            await self.scheduler.start()
            log.info("✅ Scheduler pronto")
        except Exception as e:
            log.warning("⚠️ Erro no scheduler", error=str(e))

    async def _init_telegram(self):
        """Inicializa bot Telegram"""
        if not self.config.telegram.bot_token:
            log.warning("⚠️ Token do Telegram não configurado — modo terminal")
            return
        try:
            from telegram_bot.bot import TelegramBot
            self.telegram_bot = TelegramBot(self.config.telegram, self)
            log.info("✅ Telegram bot configurado")
        except Exception as e:
            log.warning("⚠️ Erro no Telegram bot", error=str(e))
