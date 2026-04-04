"""
Open-PY — Telegram Bot (aiogram 3.x)
Frontend principal do sistema via Telegram.
"""

import os
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import BotCommand

from shared.config import TelegramConfig
from shared.logger import get_logger
from core.rate_limiter import RateLimiter
from core.audit_log import AuditLog
from core.message_queue import MessageBatcher
from core.auto_learner import AutoLearner

log = get_logger("telegram")


class TelegramBot:
    """
    Bot Telegram como frontend único do Open-PY.
    Usa aiogram 3.x com polling (padrão).
    """

    def __init__(self, config: TelegramConfig, core):
        self.config = config
        self.core = core

        self.bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.MARKDOWN
            )
        )
        self.dp = Dispatcher()

        # Rate limiter: 1 msg/s per-chat, 20 msg/s global
        self.rate_limiter = RateLimiter(
            per_chat_rate=1.0,
            per_chat_burst=5,
            global_rate=20.0,
            global_burst=30,
        )

        # Audit log
        install_dir = getattr(config, 'install_dir', '/opt/open-py')
        self.audit = AuditLog(
            log_dir=f"{core.config.core.install_dir}/data/audit"
            if hasattr(core, 'config') else "/opt/open-py/data/audit"
        )

        # Message Batcher: espera 2s para agrupar msgs antes de processar
        self.batcher = MessageBatcher(
            process_callback=self._process_batched_message,
            batch_window=2.0,
        )

        # Auto-Learner: salva tudo e aprende preferências
        self.learner = AutoLearner(
            memory_manager=core.memory_manager if hasattr(core, 'memory_manager') else None,
            db_pool=core.db_pool if hasattr(core, 'db_pool') else None,
        )

        # Cache de messages para callback
        self._pending_replies: dict[int, types.Message] = {}

        # Registrar handlers
        self._register_handlers()

    # ============================================
    # HANDLERS
    # ============================================

    def _register_handlers(self):
        """Registra todos os handlers do bot"""

        # === COMANDOS ===
        @self.dp.message(Command("start"))
        async def cmd_start(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return

            # Detectar primeiro boot (soul.md contém "PRIMEIRO BOOT")
            is_first_boot = False
            if hasattr(self.core, '_soul') and "PRIMEIRO BOOT" in (self.core._soul or ""):
                is_first_boot = True

            if is_first_boot:
                await message.reply(
                    "🌱 **Acabei de nascer!**\n\n"
                    "Sou seu novo agente autônomo. "
                    "Ainda não sei nada sobre você, mas quero aprender tudo.\n\n"
                    "Me conta:\n"
                    "1️⃣ Qual seu nome?\n"
                    "2️⃣ Onde você mora?\n"
                    "3️⃣ O que você faz (trabalho/profissão)?\n"
                    "4️⃣ Quais tecnologias/ferramentas você usa?\n"
                    "5️⃣ Como quer que eu me comporte? "
                    "(direto, detalhista, engraçado, sério...)\n"
                    "6️⃣ Qual idioma preferido?\n"
                    "7️⃣ Quer me dar um nome?\n\n"
                    "Pode responder tudo junto ou aos poucos — "
                    "eu vou guardando e aprendendo! 🧠"
                )
            else:
                await message.reply(
                    "🧠 **Open-PY v3.1** está online!\n\n"
                    "Envie qualquer mensagem, imagem, áudio ou documento.\n\n"
                    "Use /commands para ver tudo que posso fazer."
                )

        @self.dp.message(Command("help"))
        async def cmd_help(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.reply(
                "Use /commands para ver a lista completa de comandos."
            )

        @self.dp.message(Command("commands"))
        async def cmd_commands(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            text = (
                "📖 **Todos os Comandos Open-PY**\n\n"

                "🔧 **Sistema**\n"
                "/start — Iniciar o bot\n"
                "/commands — Esta lista de comandos\n"
                "/status — RAM, disco, agentes, tarefas\n"
                "/health — Healthcheck de todos os componentes\n"
                "/audit — Integridade do audit log (SHA-256)\n\n"

                "🧬 **Identidade**\n"
                "/soul — Ver memória permanente (soul.md)\n"
                "/essence — Ver personalidade (essence.md)\n\n"

                "💾 **Memória**\n"
                "/memory — Estatísticas de memória\n"
                "/remember <texto> — Salvar fato manualmente\n"
                "/recall <busca> — Buscar memórias (semântico)\n"
                "/forget <id> — Esquecer memória específica\n\n"

                "🤖 **Agentes**\n"
                "/agents — Listar agentes ativos\n"
                "/spawn <nome> — Criar agente customizado\n"
                "/kill <nome> — Destruir agente\n\n"

                "📋 **Tarefas**\n"
                "/tasks — Ver tarefas em execução\n"
                "/cancel <id> — Cancelar tarefa\n\n"

                "🔌 **Provedores & Modelos**\n"
                "/providers — Listar provedores configurados\n"
                "/provider <nome> — Trocar provedor ativo\n"
                "/model <modelo> — Trocar modelo do provedor ativo\n"
                "/addprovider <nome> <api_key> [url] — Adicionar provedor\n"
                "/addmodel <provedor> <modelo> — Definir modelo para provedor\n\n"

                "⚙️ **Config**\n"
                "/config — Ver configuração atual\n"
            )
            await message.reply(text)

        # === PROVEDORES & MODELOS ===
        @self.dp.message(Command("providers"))
        async def cmd_providers(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            if not self.core.llm_router:
                await message.reply("⚠️ Nenhum provedor LLM configurado.")
                return
            providers = self.core.llm_router.list_providers()
            if not providers:
                await message.reply("Nenhum provedor configurado.")
                return
            text = "🔌 **Provedores LLM**\n\n"
            for p in providers:
                active = " ← ATIVO" if p["active"] else ""
                emoji = "🟢" if p["active"] else "⚪"
                text += f"{emoji} **{p['name']}** — `{p['model']}`{active}\n"
            info = self.core.llm_router.get_current_info()
            text += f"\nTotal: {info['total_providers']} provedor(es)"
            await message.reply(text)

        @self.dp.message(Command("provider"))
        async def cmd_provider(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            name = message.text.replace("/provider", "").strip()
            if not name:
                # Sem argumento: mostrar ativo
                if self.core.llm_router:
                    info = self.core.llm_router.get_current_info()
                    await message.reply(
                        f"🔌 Provedor ativo: **{info['provider']}**\n"
                        f"Modelo: `{info['model']}`\n\n"
                        f"Para trocar: /provider <nome>"
                    )
                else:
                    await message.reply("⚠️ Nenhum provedor configurado.")
                return
            if not self.core.llm_router:
                await message.reply("⚠️ Nenhum provedor configurado.")
                return
            result = self.core.llm_router.set_active_provider(name)
            await message.reply(result["message"])

        @self.dp.message(Command("model"))
        async def cmd_model(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            model = message.text.replace("/model", "").strip()
            if not model:
                if self.core.llm_router:
                    info = self.core.llm_router.get_current_info()
                    await message.reply(
                        f"🤖 Modelo atual: `{info['model']}`\n"
                        f"Provedor: **{info['provider']}**\n\n"
                        f"Para trocar: /model <nome_do_modelo>"
                    )
                else:
                    await message.reply("⚠️ Nenhum provedor configurado.")
                return
            if not self.core.llm_router:
                await message.reply("⚠️ Nenhum provedor configurado.")
                return
            result = self.core.llm_router.set_model(model)
            await message.reply(result["message"])

        @self.dp.message(Command("addprovider"))
        async def cmd_addprovider(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            parts = message.text.replace("/addprovider", "").strip().split()
            if len(parts) < 2:
                await message.reply(
                    "Use: /addprovider <nome> <api_key> [api_base]\n\n"
                    "Exemplos:\n"
                    "`/addprovider openrouter sk-or-xxx`\n"
                    "`/addprovider openai sk-xxx`\n"
                    "`/addprovider nvidia nvapi-xxx https://integrate.api.nvidia.com/v1`"
                )
                return
            name = parts[0].lower()
            api_key = parts[1]
            api_base = parts[2] if len(parts) > 2 else None

            if not self.core.llm_router:
                await message.reply("⚠️ Sistema de LLM não inicializado.")
                return

            result = self.core.llm_router.add_provider(name, api_key, api_base=api_base)
            await message.reply(result["message"])

            # Audit log
            try:
                await self.audit.log(
                    actor=f"user:{message.from_user.id}",
                    action="add_provider",
                    target=name,
                    severity="info",
                )
            except Exception:
                pass

        @self.dp.message(Command("addmodel"))
        async def cmd_addmodel(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            parts = message.text.replace("/addmodel", "").strip().split(maxsplit=1)
            if len(parts) < 2:
                await message.reply(
                    "Use: /addmodel <provedor> <modelo>\n\n"
                    "Exemplos:\n"
                    "`/addmodel openrouter qwen/qwen3-235b-a22b:free`\n"
                    "`/addmodel openai gpt-4o`\n"
                    "`/addmodel anthropic claude-sonnet-4-20250514`"
                )
                return
            provider = parts[0].lower()
            model = parts[1].strip()

            if not self.core.llm_router:
                await message.reply("⚠️ Sistema de LLM não inicializado.")
                return

            result = self.core.llm_router.set_model(model, provider=provider)
            await message.reply(result["message"])

        @self.dp.message(Command("status"))
        async def cmd_status(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            status = await self.core.get_system_status()
            
            # Status da Fila (TaskQueue)
            q_stats = self.queue.get_stats()
            queue_info = f"📋 Fila: {q_stats['queue_size']} | Executando: {q_stats['running']}\n"
            if q_stats["running_details"]:
                for detail in q_stats["running_details"]:
                    queue_info += f"   • {detail['text']}...\n"

            # Info de provedor ativo
            provider_info = ""
            if self.core.llm_router:
                info = self.core.llm_router.get_current_info()
                provider_info = (
                    f"🔌 Provedor: {info['provider']}\n"
                    f"🤖 Modelo: `{info['model']}`\n"
                )
            text = (
                "📊 **Status Open-PY v3.1**\n\n"
                f"{provider_info}"
                f"🧠 Memórias: {status['memory_count']}\n"
                f"🤖 Agentes: {status['active_agents']}\n"
                f"{queue_info}"
                f"💾 RAM: {status['ram_used_pct']}%\n"
                f"💿 Disco: {status['disk_used_pct']}%\n"
                f"💓 Heartbeat: {status['last_heartbeat']}\n"
            )
            await message.reply(text)

        @self.dp.message(Command("health"))
        async def cmd_health(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            report = await self.core.get_health_report()
            status_emoji = {"healthy": "🟢", "degraded": "🟡", "down": "🔴"}.get(
                report.get("status", ""), "⚪"
            )
            text = f"{status_emoji} **Healthcheck Open-PY**\n\n"
            for comp, info in report.get("components", {}).items():
                if isinstance(info, dict) and "status" in info:
                    emoji = {"up": "🟢", "down": "🔴", "not_configured": "⚪"}.get(
                        info["status"], "🟡"
                    )
                    text += f"{emoji} **{comp}**: {info['status']}\n"
                elif isinstance(info, dict):
                    # Agent health report
                    text += f"\n🤖 **Saúde dos Agentes:**\n"
                    for agent_name, health in info.items():
                        h_emoji = "🟢" if health.get("healthy") else "🔴"
                        fails = health.get("failures", 0)
                        text += f"  {h_emoji} {agent_name} — {fails} falhas\n"
            await message.reply(text)

        @self.dp.message(Command("agents"))
        async def cmd_agents(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            agents = self.core.agent_registry.list_all() if self.core.agent_registry else []
            if not agents:
                await message.reply("Nenhum agente ativo.")
                return
            text = "🤖 **Agentes Ativos**\n\n"
            for a in agents:
                status_emoji = {"idle": "🟢", "running": "🟡", "error": "🔴"}.get(a["status"], "⚪")
                text += f"{status_emoji} **{a['name']}** — {a['description']}\n"
            await message.reply(text)

        @self.dp.message(Command("memory"))
        async def cmd_memory(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            stats = await self.core.memory_manager.get_stats() if self.core.memory_manager else {}
            text = (
                "💾 **Memória Open-PY**\n\n"
                f"Total no PostgreSQL: {stats.get('total', 0)}\n"
                f"Hoje: {stats.get('today', 0)}\n"
                f"Tags únicas: {stats.get('unique_tags', 0)}\n"
                f"Buffer atual: {stats.get('buffer_size', 0)} interações "
                f"({stats.get('buffer_tokens', 0)} tokens)\n"
                f"Arquivos .md pendentes: {stats.get('md_files', 0)}\n"
            )
            await message.reply(text)

        @self.dp.message(Command("remember"))
        async def cmd_remember(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            text = message.text.replace("/remember", "").strip()
            if not text:
                await message.reply("Use: /remember <texto para lembrar>")
                return
            if self.core.memory_manager:
                await self.core.memory_manager.save_memory(
                    content=text, content_type="fact",
                    source="user", tags=["manual"],
                    importance=7,
                )
            await message.reply(f"💾 Memória salva: _{text[:100]}_")

        @self.dp.message(Command("recall"))
        async def cmd_recall(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            query = message.text.replace("/recall", "").strip()
            if not query:
                await message.reply("Use: /recall <busca>")
                return
            if self.core.memory_manager:
                results = await self.core.memory_manager.search(query, mode="hybrid", limit=5)
                if results:
                    text = "🔍 **Memórias encontradas**\n\n"
                    for r in results:
                        text += f"• {r['content'][:200]}\n\n"
                    await message.reply(text)
                else:
                    await message.reply("Nenhuma memória encontrada.")
            else:
                await message.reply("⚠️ Sistema de memória indisponível")

        @self.dp.message(Command("tasks"))
        async def cmd_tasks(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            tasks = await self.core.orchestrator.get_active_tasks() if self.core.orchestrator else []
            if not tasks:
                await message.reply("Nenhuma tarefa ativa.")
                return
            text = "📋 **Tarefas Ativas**\n\n"
            for t in tasks:
                text += f"• `{t['task_id']}` — {t['task'][:80]}\n"
            await message.reply(text)

        @self.dp.message(Command("soul"))
        async def cmd_soul(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.reply(f"🧬 **Soul.md**\n\n{self.core._soul[:3000]}")

        @self.dp.message(Command("essence"))
        async def cmd_essence(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.reply(f"🎭 **Essence.md**\n\n{self.core._essence[:3000]}")

        @self.dp.message(Command("debug"))
        async def cmd_debug(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            
            # Coletar infos internas
            q_stats = self.queue.get_stats()
            b_stats = self.batcher.get_stats()
            m_stats = await self.core.memory_manager.get_stats() if self.core.memory_manager else {}
            
            text = (
                "🧪 **Diagnostic mode on**\n\n"
                f"**Task Queue:**\n"
                f"• Pendentes: {q_stats['queue_size']}\n"
                f"• Processando: {q_stats['running']}\n"
                f"• Total histórico: {q_stats['total_processed']}\n\n"
                f"**Message Batcher:**\n"
                f"• Chats ativos: {b_stats['pending_chats']}\n"
                f"• Timers: {b_stats['active_timers']}\n\n"
                f"**Memory Engine:**\n"
                f"• Buffer: {m_stats.get('buffer_size', 0)} / 20\n"
                f"• Last Compact: {m_stats.get('last_compact', 'Nunca')}\n"
            )
            await message.reply(text)

        # === AUDIT ===
        @self.dp.message(Command("audit"))
        async def cmd_audit(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            chain = await self.audit.verify_chain()
            stats = await self.audit.get_stats()
            chain_emoji = "🟢" if chain["valid"] else "🔴"
            text = (
                f"{chain_emoji} **Audit Log**\n\n"
                f"Chain: {'Válida' if chain['valid'] else 'CORROMPIDA'}\n"
                f"Entradas hoje: {chain['entries']}\n"
                f"Total histórico: {stats.get('total_entries', 0)}\n"
                f"Arquivos: {stats.get('total_files', 0)}\n"
            )
            if not chain["valid"]:
                text += f"\n⚠️ Quebra detectada na entrada {chain['broken_at']}\n"
                text += f"Razão: {chain.get('reason', 'desconhecida')}\n"
            # Últimas entradas
            recent = await self.audit.get_recent(5)
            if recent:
                text += "\n**Últimas ações:**\n"
                for entry in recent:
                    text += f"• `{entry['action']}` por {entry['actor']} → {entry.get('target', '-')}\n"
            await message.reply(text)

        # === MENSAGENS DE TEXTO (catch-all) ===
        @self.dp.message(F.text)
        async def handle_text(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return

            # Rate limit check
            check = await self.rate_limiter.check(
                chat_id=message.chat.id,
                message_text=message.text,
            )
            if not check["allowed"]:
                if check["reason"] == "duplicate":
                    return  # Silenciosamente ignora duplicatas
                await message.reply(
                    f"⚠️ Rate limit atingido. Tente novamente em "
                    f"{check['retry_after']:.1f}s"
                )
                return

            # Guardar referência da mensagem para reply posterior
            self._pending_replies[message.chat.id] = message

            # Enviar ao batcher (agrupa msgs em janela de 2s)
            await self.batcher.add_message(
                chat_id=message.chat.id,
                message={
                    "text": message.text,
                    "input_type": "text",
                    "user_id": message.from_user.id,
                    "attachments": [],
                }
            )

        # === FOTOS ===
        @self.dp.message(F.photo)
        async def handle_photo(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.chat.do("typing")
            photo = message.photo[-1]
            file_path = await self._download_file(photo.file_id, "photo")
            caption = message.caption or "Analise esta imagem"
            result = await self.core.process(
                input_text=caption,
                input_type="image",
                attachments=[file_path] if file_path else [],
                user_id=message.from_user.id,
            )
            await self._send_long_message(message, result.get("response", ""))

        # === ÁUDIO / VOZ ===
        @self.dp.message(F.audio | F.voice)
        async def handle_audio(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.chat.do("typing")
            file_id = (message.audio or message.voice).file_id
            file_path = await self._download_file(file_id, "audio")
            result = await self.core.process(
                input_text=message.caption or "Transcreva este áudio",
                input_type="audio",
                attachments=[file_path] if file_path else [],
                user_id=message.from_user.id,
            )
            await self._send_long_message(message, result.get("response", ""))

        # === DOCUMENTOS ===
        @self.dp.message(F.document)
        async def handle_document(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.chat.do("typing")
            file_path = await self._download_file(message.document.file_id, "document")
            result = await self.core.process(
                input_text=message.caption or "Analise este documento",
                input_type="document",
                attachments=[file_path] if file_path else [],
                user_id=message.from_user.id,
            )
            await self._send_long_message(message, result.get("response", ""))

        # === VÍDEO ===
        @self.dp.message(F.video | F.video_note)
        async def handle_video(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.chat.do("typing")
            vid = message.video or message.video_note
            file_path = await self._download_file(vid.file_id, "video")
            result = await self.core.process(
                input_text=message.caption or "Analise este vídeo",
                input_type="video",
                attachments=[file_path] if file_path else [],
                user_id=message.from_user.id,
            )
            await self._send_long_message(message, result.get("response", ""))

    # ============================================
    # BATCH PROCESSOR (chamado pelo MessageBatcher)
    # ============================================

    async def _process_batched_message(self, chat_id: int, msg_data: dict):
        """
        Versão Refatorada (Fase 10): Enfileira a tarefa na TaskQueue.
        """
        message = self._pending_replies.get(chat_id)
        if not message:
            return

        input_text = msg_data.get("text", "")
        user_id = msg_data.get("user_id", 0)

        # Definir callback para processar o resultado
        async def on_complete(result: dict):
            response = result.get("response", "⚠️ Sem resposta do core.")
            await self._send_long_message(message, response)
            
            # Learner (background)
            asyncio.create_task(self.learner.learn_from_interaction(
                user_input=input_text,
                bot_response=response,
                user_id=user_id,
                input_type=msg_data.get("input_type", "text")
            ))

        # Criar tarefa para a fila
        from core.message_queue import QueuedTask, Priority
        import uuid
        
        task = QueuedTask(
            task_id=f"msg-{uuid.uuid4().hex[:8]}",
            priority=Priority.NORMAL,
            input_text=input_text,
            input_type=msg_data.get("input_type", "text"),
            attachments=msg_data.get("attachments", []),
            user_id=user_id,
            callback=on_complete
        )

        # Typing sustentado
        async def typing_loop():
            try:
                # Enquanto a tarefa existir em running ou queue
                found = True
                while found:
                    stats = self.queue.get_stats()
                    found = any(t["id"] == task.task_id for t in stats["running_details"]) or \
                            stats["queue_size"] > 0 # Simplificado
                    
                    if not found: break
                    await message.chat.do("typing")
                    await asyncio.sleep(5)
            except Exception:
                pass

        asyncio.create_task(typing_loop())
        await self.queue.enqueue(task)

    async def _core_processor(self, task: QueuedTask) -> dict:
        """Chamado pela TaskQueue para processar a tarefa no Core"""
        try:
            return await self.core.process(
                input_text=task.input_text,
                input_type=task.input_type,
                user_id=task.user_id,
                attachments=task.attachments,
            )
        except Exception as e:
            log.error("Erro no Core Processor", error=str(e))
            return {"response": f"❌ Erro interno: {str(e)}", "status": "error"}

    # ============================================
    # AUTH
    # ============================================

    def _is_authorized(self, user_id: int) -> bool:
        """Verifica se o usuário está autorizado"""
        if not self.config.allowed_users:
            return True  # Sem lista = aceita qualquer um
        return user_id in self.config.allowed_users

    # ============================================
    # HELPERS
    # ============================================

    async def _download_file(self, file_id: str, media_type: str) -> str:
        """Faz download de arquivo do Telegram"""
        try:
            install_dir = self.core.config.core.install_dir
            media_dir = Path(install_dir) / "data" / "media" / media_type
            media_dir.mkdir(parents=True, exist_ok=True)

            file = await self.bot.get_file(file_id)
            ext = os.path.splitext(file.file_path or "")[1] or ".bin"
            local_path = str(media_dir / f"{file_id}{ext}")

            await self.bot.download_file(file.file_path, local_path)
            log.info("📥 Arquivo baixado", path=local_path)
            return local_path
        except Exception as e:
            log.error("❌ Erro no download", error=str(e))
            return ""

    async def _send_long_message(self, message: types.Message, text: str):
        """Envia mensagem longa dividida em chunks"""
        max_len = self.config.max_message_length
        if len(text) <= max_len:
            await message.reply(text)
            return

        chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)]
        for chunk in chunks:
            await message.reply(chunk)

    # ============================================
    # LIFECYCLE
    # ============================================

    async def start_polling(self):
        """Inicia polling do bot"""
        # Registrar comandos no menu
        commands = [
            BotCommand(command="start", description="Iniciar bot"),
            BotCommand(command="commands", description="Lista completa de comandos"),
            BotCommand(command="status", description="Status do sistema"),
            BotCommand(command="health", description="Healthcheck completo"),
            BotCommand(command="providers", description="Listar provedores LLM"),
            BotCommand(command="provider", description="Trocar provedor ativo"),
            BotCommand(command="model", description="Trocar modelo ativo"),
            BotCommand(command="memory", description="Stats de memória"),
            BotCommand(command="agents", description="Listar agentes"),
            BotCommand(command="tasks", description="Tarefas ativas"),
            BotCommand(command="remember", description="Salvar memória"),
            BotCommand(command="recall", description="Buscar memórias"),
            BotCommand(command="audit", description="Audit log (SHA-256)"),
            BotCommand(command="soul", description="Ver soul.md"),
            BotCommand(command="essence", description="Ver essence.md"),
        ]
        await self.bot.set_my_commands(commands)

        log.info("📱 Telegram bot iniciando polling...")
        await self.dp.start_polling(self.bot)

    async def stop(self):
        """Para o bot"""
        await self.dp.stop_polling()
        await self.bot.session.close()
        log.info("📱 Telegram bot parado")
