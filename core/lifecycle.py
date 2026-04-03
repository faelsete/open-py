"""
Open-PY — Lifecycle Manager
Controla startup, running e shutdown do sistema inteiro.
"""

import asyncio
import signal
import os
from pathlib import Path
from typing import Optional

import asyncpg

from shared.config import load_config, OpenPYConfig
from shared.logger import setup_logging, get_logger
from shared.migrations import run_migrations
from core.brain import ThinkingEngine, build_core_system_prompt

log = get_logger("lifecycle")


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

        # 6. Thinking Engine
        self.brain = ThinkingEngine(
            llm_router=self.llm_router,
            memory_manager=self.memory_manager,
            agent_registry=self.agent_registry,
        )
        log.info("✅ Thinking Engine pronto")

        # 7. Sistema de agentes
        await self._init_agents()

        # 8. Orchestrator
        from core.orchestrator import Orchestrator
        self.orchestrator = Orchestrator(
            agent_registry=self.agent_registry,
            agent_factory=self.agent_factory,
            memory_manager=self.memory_manager,
            db_pool=self.db_pool,
        )
        log.info("✅ Orchestrator pronto")

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
        Chamado pelo Telegram handler ou por comandos internos.
        """
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

        # Se tem agente alvo, delegar
        if thinking.target_agent:
            result = await self.orchestrator.dispatch(thinking, attachments)
            return {
                "response": result.output or result.error or "Sem resultado",
                "task_id": result.task_id,
                "status": result.status.value,
                "delegated_to": thinking.target_agent,
            }

        # Senão, Core responde diretamente via LLM
        if self.llm_router:
            system_prompt = build_core_system_prompt(self._soul, self._essence)
            response = await self.llm_router.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": input_text},
                ],
            )
            # Salvar memória da interação
            if self.memory_manager:
                await self.memory_manager.buffer_interaction(input_text, response)

            return {"response": response, "status": "completed"}

        return {"response": "⚠️ Nenhum provedor LLM configurado. Use /config.", "status": "error"}

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
        """Carrega soul.md e essence.md"""
        data_dir = Path(self.config.core.install_dir) / "data"

        soul_path = data_dir / "soul.md"
        essence_path = data_dir / "essence.md"

        if soul_path.exists():
            self._soul = soul_path.read_text(encoding="utf-8")
            log.info("✅ soul.md carregado")
        else:
            self._soul = "Nenhuma memória permanente registrada ainda."
            log.warning("⚠️ soul.md não encontrado")

        if essence_path.exists():
            self._essence = essence_path.read_text(encoding="utf-8")
            log.info("✅ essence.md carregado")
        else:
            self._essence = "Você é o Open-PY, assistente autônomo. Responda em português brasileiro de forma direta e objetiva."
            log.warning("⚠️ essence.md não encontrado, usando default")

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
        """Inicializa registry e factory de agentes"""
        try:
            from agents.registry import AgentRegistry
            from agents.factory import AgentFactory
            self.agent_registry = AgentRegistry()
            self.agent_factory = AgentFactory(
                registry=self.agent_registry,
                config=self.config,
                llm_router=self.llm_router,
            )
            log.info("✅ Sistema de agentes pronto")
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
