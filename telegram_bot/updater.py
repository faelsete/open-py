import asyncio
import time
from typing import Optional
from aiogram import types
from shared.logger import get_logger

log = get_logger("updater")

class MessageUpdater:
    """
    Gerencia atualizações de mensagens no Telegram para evitar limites de taxa (Rate Limit).
    Faz "batching" de edições e garante que a mensagem seja atualizada em intervalos seguros.
    """
    def __init__(self, message: types.Message, update_interval: float = 1.0):
        self.message = message
        self.update_interval = update_interval
        self._current_text = ""
        self._last_update_time = 0.0
        self._pending_update = False
        self._reply_msg: Optional[types.Message] = None
        self._lock = asyncio.Lock()
        self._closed = False
        
    async def update(self, new_text: str):
        """Acumula texto para atualização e dispara update se o intervalo passou."""
        if self._closed:
            return
            
        async with self._lock:
            # Se for o mesmo texto, não faz nada
            if new_text == self._current_text:
                return
                
            self._current_text = new_text
            self._pending_update = True
        
        now = time.time()
        if now - self._last_update_time >= self.update_interval:
            # Tempo suficiente passou, dar update agora em background
            asyncio.create_task(self._do_update())

    async def _do_update(self):
        """Realiza a edição da mensagem de fato no Telegram."""
        async with self._lock:
            if not self._pending_update or self._closed:
                return
            
            text_to_send = self._current_text
            self._pending_update = False
            self._last_update_time = time.time()

        try:
            if not self._reply_msg:
                # Primeira vez: responde à mensagem
                self._reply_msg = await self.message.reply(text_to_send or "...") 
            else:
                # Atualizações subsequentes: edita a mensagem
                await self._reply_msg.edit_text(text_to_send)
        except Exception as e:
            err = str(e).lower()
            if "message is not modified" in err:
                pass
            elif "parse entities" in err or "unsupported start tag" in err:
                try:
                    if not self._reply_msg:
                        self._reply_msg = await self.message.reply(text_to_send or "...", parse_mode=None)
                    else:
                        await self._reply_msg.edit_text(text_to_send, parse_mode=None)
                except Exception as e2:
                    log.warning("Falha severa ao atualizar mensagem (fallback)", error=str(e2))
            else:
                log.warning("Falha ao atualizar mensagem no Telegram", error=str(e))

    async def finalize(self):
        """Garante que a última versão enviada seja a definitiva."""
        if self._closed:
            return
            
        async with self._lock:
            self._closed = True
            
        # Garante o último update imediatamente (ignora o timeout)
        try:
            if not self._reply_msg:
                if self._current_text:
                    self._reply_msg = await self.message.reply(self._current_text)
            else:
                await self._reply_msg.edit_text(self._current_text)
        except Exception as e:
            err = str(e).lower()
            if "message is not modified" not in err:
                if "parse entities" in err or "unsupported start tag" in err:
                    try:
                        if not self._reply_msg:
                            self._reply_msg = await self.message.reply(self._current_text, parse_mode=None)
                        else:
                            await self._reply_msg.edit_text(self._current_text, parse_mode=None)
                    except Exception as e2:
                        log.error("Erro duplo no finalize do MessageUpdater (fallback)", error=str(e2))
                else:
                    log.error("Erro no finalize do MessageUpdater", error=str(e))

