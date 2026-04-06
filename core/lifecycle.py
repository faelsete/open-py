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

        # v3.0: Novos subsistemas
        self.pipeline = None
        self.validator = None
        self.extractor = None
        self.feedback_loop = None

        # Histórico conversacional por usuário (RAM)
        # Chave: user_id (int) → Valor: lista de {role, content}
        self._conversation_histories: dict[int, list[dict]] = {}
        
        # Guardar pendentes para confirmação
        self._pending_creations: dict[int, dict] = {}

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

        # 9. v3.0: Validator (Quality Gate)
        from core.validator import ResponseValidator
        self.validator = ResponseValidator(
            config=self.config.validator,
            llm_router=self.llm_router,
        )
        log.info("✅ Validator (Quality Gate) pronto")

        # 10. v3.0: Memory Extractor (Background)
        from memory.extractor import MemoryExtractor
        self.extractor = MemoryExtractor(
            config=self.config.memory,
            llm_router=self.llm_router,
            memory_manager=self.memory_manager,
        )
        log.info("✅ Memory Extractor pronto")

        # 11. v3.0: Pipeline (Túnel Rígido)
        from core.pipeline import ExecutionPipeline
        self.pipeline = ExecutionPipeline(
            config=self.config,
            brain=self.brain,
            orchestrator=self.orchestrator,
            memory_manager=self.memory_manager,
            llm_router=self.llm_router,
            validator=self.validator,
        )
        log.info("✅ Pipeline v3.0 pronto (6 gates)")

        # 12. v3.0: Feedback Loop
        from core.feedback_loop import FeedbackLoop
        self.feedback_loop = FeedbackLoop(
            llm_router=self.llm_router,
            memory_manager=self.memory_manager,
            pipeline=self.pipeline,
            orchestrator=self.orchestrator,
            validator=self.validator,
        )
        log.info("✅ Feedback Loop pronto")

        # 13. Scheduler (heartbeat + cron)
        await self._init_scheduler()

        # 14. Telegram Bot
        await self._init_telegram()
        
        # Injetar LLM router na Memória para Compactação
        if self.memory_manager and self.llm_router:
            self.memory_manager.llm_router = self.llm_router

        self._running = True
        log.info("🚀 Open-PY v3.0 pronto e operacional! (Pipeline + Quality Gate + Feedback Loop)")

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
        v3.0: Ponto de entrada via Pipeline de 6 Gates.
        
        Fluxo:
        1. Comandos especiais (/remember, confirmações)
        2. Pipeline: Capture → Memory → Route → Prepare → Execute → Validate
        3. Pós-processamento: salvar histórico, trigger extractors e feedback
        """
        try:
            # === COMANDO REMEMBER ===
            if input_text.startswith("/remember"):
                content = input_text[9:].strip()
                if self.memory_manager:
                    await self.memory_manager.save_memory(
                        content=content,
                        source="user",
                        tags=["importante", "manual"],
                        importance=10
                    )
                return {
                    "response": f"✅ Memória salva com sucesso!\n\n_{content}_",
                    "status": "completed",
                    "task_id": None
                }
                
            # === CONFIRMAÇÃO PENDENTE ===
            if user_id in self._pending_creations:
                spec = self._pending_creations.pop(user_id)
                text_lower = input_text.strip().lower()
                if text_lower in ["sim", "s", "yes", "y", "confirmo", "criar"]:
                    agent = await self.agent_factory.create_custom(spec)
                    if agent:
                        response_text = f"✅ Agente customizado '{agent.config.name}' criado com sucesso!"
                    else:
                        response_text = "❌ Falha ao criar agente customizado."
                else:
                    response_text = "❌ Criação do agente cancelada."
                    
                self._add_to_conversation(user_id, "user", input_text)
                self._add_to_conversation(user_id, "assistant", response_text)
                return {"response": response_text, "status": "completed"}

            # === v3.0: PIPELINE DE 6 GATES ===
            history = self._get_conversation_history(user_id)
            
            pipeline_result = await self.pipeline.run(
                raw_input=input_text,
                input_type=input_type,
                attachments=attachments,
                user_id=user_id,
                conversation_history=history,
                soul=self._soul,
                essence=self._essence,
            )

            if not pipeline_result.success:
                error_msg = f"⚠️ Pipeline falhou no gate '{pipeline_result.failed_gate}': {pipeline_result.error}"
                log.error(error_msg)
                return {"response": error_msg, "status": "error"}

            response_text = pipeline_result.response

            # === PÓS-PROCESSAMENTO ===

            # Agent Creator flow (pending confirmation)
            if pipeline_result.delegated_to == "agent_creator":
                import json as _json
                import re as _re
                try:
                    json_str = response_text
                    match = _re.search(r'```(?:json)?(.*?)```', json_str, _re.DOTALL)
                    if match:
                        json_str = match.group(1).strip()
                    spec = _json.loads(json_str)
                    self._pending_creations[user_id] = spec
                    response_text = (f"⚙️ Spec do agente gerada!\n"
                                    f"```json\n{_json.dumps(spec, indent=2)}\n```\n"
                                    f"\nDeseja criar este agente? (SIM ou NÃO)")
                    self._add_to_conversation(user_id, "user", input_text)
                    self._add_to_conversation(user_id, "assistant", "Spec gerada. Aguardando confirmação.")
                    return {"response": response_text, "status": "waiting",
                            "delegated_to": "agent_creator"}
                except Exception:
                    pass  # Não é agent_creator, prosseguir normalmente

            # Salvar no histórico conversacional (RAM)
            self._add_to_conversation(user_id, "user", input_text)
            self._add_to_conversation(user_id, "assistant", response_text)

            # Salvar na memória de longo prazo
            if self.memory_manager:
                await self.memory_manager.buffer_interaction(input_text, response_text)

            # v3.0: Trigger extração de memórias em background
            if self.extractor and self.memory_manager:
                self.extractor.record_interaction(
                    tokens=self.memory_manager._buffer_tokens
                )
                await self.extractor.maybe_extract(
                    self.memory_manager._buffer,
                    self.memory_manager._buffer_tokens
                )

            # v3.0: Trigger feedback loop
            if self.feedback_loop:
                validate_gate = pipeline_result.gates.get("validate")
                validated = validate_gate and not validate_gate.skipped if validate_gate else True
                self.feedback_loop.record_interaction(
                    user_input=input_text,
                    response=response_text,
                    input_type=input_type,
                    delegated_to=pipeline_result.delegated_to,
                    validated=validated,
                    duration_ms=pipeline_result.total_duration_ms,
                )
                await self.feedback_loop.maybe_analyze()

            return {
                "response": response_text,
                "status": pipeline_result.gates.get("execute", {}).data.get("status", "completed") if pipeline_result.gates.get("execute") and pipeline_result.gates["execute"].data else "completed",
                "task_id": pipeline_result.task_id,
                "delegated_to": pipeline_result.delegated_to,
                "pipeline_ms": pipeline_result.total_duration_ms,
            }

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
        """Inicializa sistema de memória (v3.0: com suporte a Ollama)"""
        try:
            from memory.manager import MemoryManager
            self.memory_manager = MemoryManager(
                db_pool=self.db_pool,
                config=self.config.memory,
                install_dir=self.config.core.install_dir,
                ollama_config=self.config.ollama,  # v3.0: Ollama para embeddings
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
