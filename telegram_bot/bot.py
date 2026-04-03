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
            await message.reply(
                "🧠 **Open-PY v1.0** está online!\n\n"
                "Envie qualquer mensagem, imagem, áudio ou documento.\n"
                "Use /help para ver todos os comandos."
            )

        @self.dp.message(Command("help"))
        async def cmd_help(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            help_text = (
                "📖 **Comandos Open-PY**\n\n"
                "**Sistema**\n"
                "/status — Status do sistema\n"
                "/doctor — Diagnóstico completo\n"
                "/soul — Ver soul.md\n"
                "/essence — Ver essence.md\n\n"
                "**Memória**\n"
                "/memory — Stats de memória\n"
                "/remember <texto> — Salvar memória\n"
                "/recall <busca> — Buscar memórias\n"
                "/forget <id> — Esquecer memória\n\n"
                "**Agentes**\n"
                "/agents — Listar agentes\n"
                "/spawn <nome> — Criar agente\n"
                "/kill <nome> — Destruir agente\n\n"
                "**Tarefas**\n"
                "/tasks — Tarefas ativas\n"
                "/cancel <id> — Cancelar tarefa\n\n"
                "**Config**\n"
                "/config — Ver configuração\n"
            )
            await message.reply(help_text)

        @self.dp.message(Command("status"))
        async def cmd_status(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            status = await self.core.get_system_status()
            text = (
                "📊 **Status Open-PY**\n\n"
                f"🧠 Memórias: {status['memory_count']}\n"
                f"🤖 Agentes: {status['active_agents']}\n"
                f"📋 Tarefas: {status['pending_tasks']}\n"
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

        # === MENSAGENS DE TEXTO (catch-all) ===
        @self.dp.message(F.text)
        async def handle_text(message: types.Message):
            if not self._is_authorized(message.from_user.id):
                return
            await message.chat.do("typing")
            result = await self.core.process(
                input_text=message.text,
                input_type="text",
                user_id=message.from_user.id,
            )
            response = result.get("response", "Sem resposta")
            # Dividir se muito longo
            await self._send_long_message(message, response)

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
            BotCommand(command="help", description="Ajuda"),
            BotCommand(command="status", description="Status do sistema"),
            BotCommand(command="health", description="Healthcheck completo"),
            BotCommand(command="memory", description="Stats de memória"),
            BotCommand(command="agents", description="Listar agentes"),
            BotCommand(command="tasks", description="Tarefas ativas"),
            BotCommand(command="remember", description="Salvar memória"),
            BotCommand(command="recall", description="Buscar memórias"),
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
