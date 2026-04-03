"""
Open-PY — Message Batcher & Task Queue
Resolve os problemas de:
1. Respostas fragmentadas (10 msgs → 10 respostas independentes)
2. Falta de fila de tarefas com prioridade
3. Mudança de assunto sem detecção

Fluxo:
- Mensagem chega → entra no Batcher
- Batcher espera 2s (BATCH_WINDOW) por mais mensagens
- Após 2s sem nova msg → concatena tudo → envia ao Core como 1 input
- Core processa → resposta única e coerente

Task Queue:
- FIFO com prioridade (CRITICAL > HIGH > NORMAL > LOW)
- Apenas 1 tarefa executa por vez (sequencial para coerência)
- Se muda de assunto, prioriza a nova urgência
"""

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Callable, Optional, Any

from shared.logger import get_logger

log = get_logger("batcher")

# Tempo de espera para agrupar mensagens (segundos)
BATCH_WINDOW = 2.0

# Máximo de mensagens em um batch
MAX_BATCH_SIZE = 20


class Priority(IntEnum):
    """Prioridade da tarefa (menor = mais urgente)"""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class QueuedTask:
    """Tarefa na fila"""
    task_id: str
    priority: Priority
    input_text: str
    input_type: str = "text"
    attachments: list[str] = field(default_factory=list)
    user_id: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    callback: Optional[Callable] = None  # Para enviar resposta de volta

    def __lt__(self, other):
        """Ordenação por prioridade (menor = mais urgente)"""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class MessageBatcher:
    """
    Agrupa mensagens sequenciais do mesmo chat antes de processar.
    
    Se o usuário envia 5 mensagens em 2 segundos, o batcher:
    1. Coleta todas
    2. Une em uma só
    3. Envia ao Core como input único
    4. Core responde uma vez, cobrindo tudo
    """

    def __init__(self, process_callback: Callable, batch_window: float = BATCH_WINDOW):
        self.process_callback = process_callback
        self.batch_window = batch_window
        
        # Buffer per-chat: {chat_id: [messages]}
        self._buffers: dict[int, list[dict]] = defaultdict(list)
        self._timers: dict[int, asyncio.Task] = {}
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def add_message(self, chat_id: int, message: dict):
        """
        Adiciona mensagem ao buffer do chat.
        Se já tem timer rodando, reseta.
        Após batch_window sem novas msgs, processa o batch.
        """
        async with self._locks[chat_id]:
            self._buffers[chat_id].append(message)

            # Cancelar timer anterior se existir
            if chat_id in self._timers:
                self._timers[chat_id].cancel()

            # Verificar se atingiu limite de batch
            if len(self._buffers[chat_id]) >= MAX_BATCH_SIZE:
                log.info("📦 Batch cheio, processando imediatamente",
                        chat_id=chat_id, count=len(self._buffers[chat_id]))
                await self._process_batch(chat_id)
                return

            # Iniciar novo timer
            self._timers[chat_id] = asyncio.create_task(
                self._batch_timer(chat_id)
            )

    async def _batch_timer(self, chat_id: int):
        """Espera batch_window e processa"""
        try:
            await asyncio.sleep(self.batch_window)
            async with self._locks[chat_id]:
                await self._process_batch(chat_id)
        except asyncio.CancelledError:
            pass  # Timer cancelado por nova mensagem — normal

    async def _process_batch(self, chat_id: int):
        """Processa todas as mensagens acumuladas do chat"""
        messages = self._buffers.pop(chat_id, [])
        self._timers.pop(chat_id, None)

        if not messages:
            return

        log.info("📦 Processando batch",
                 chat_id=chat_id, messages=len(messages))

        if len(messages) == 1:
            # Mensagem única — processar diretamente
            await self.process_callback(chat_id, messages[0])
        else:
            # Múltiplas mensagens — combinar em uma
            combined = self._combine_messages(messages)
            await self.process_callback(chat_id, combined)

    def _combine_messages(self, messages: list[dict]) -> dict:
        """
        Combina múltiplas mensagens em uma única.
        Preserva attachments e detecta mudanças de assunto.
        """
        texts = []
        all_attachments = []
        input_types = set()

        for i, msg in enumerate(messages, 1):
            text = msg.get("text", "")
            if text:
                texts.append(f"[Mensagem {i}]: {text}")
            
            attachments = msg.get("attachments", [])
            all_attachments.extend(attachments)
            
            input_types.add(msg.get("input_type", "text"))

        combined_text = "\n".join(texts)

        # Detectar tipo predominante
        # Se tem mídia, mídia tem prioridade
        if "image" in input_types:
            combined_type = "image"
        elif "audio" in input_types:
            combined_type = "audio"
        elif "document" in input_types:
            combined_type = "document"
        elif "code" in input_types:
            combined_type = "code"
        else:
            combined_type = "text"

        # Adicionar contexto sobre batch
        header = (
            f"[O usuário enviou {len(messages)} mensagens seguidas. "
            f"Leia TODAS antes de responder. Responda de forma unificada]\n\n"
        )

        return {
            "text": header + combined_text,
            "input_type": combined_type,
            "attachments": all_attachments,
            "user_id": messages[0].get("user_id", 0),
            "callback": messages[-1].get("callback"),  # Callback do último msg
            "is_batch": True,
            "batch_size": len(messages),
        }

    def get_stats(self) -> dict:
        """Stats do batcher"""
        return {
            "pending_chats": len(self._buffers),
            "pending_messages": sum(len(msgs) for msgs in self._buffers.values()),
            "active_timers": len(self._timers),
        }


class TaskQueue:
    """
    Fila de tarefas com prioridade.
    
    - FIFO dentro da mesma prioridade
    - CRITICAL sempre processa primeiro
    - Apenas 1 tarefa por vez (evita respostas confusas)
    - Se muda de assunto com urgência, nova tarefa pula na fila
    """

    def __init__(self, max_concurrent: int = 1):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._max_concurrent = max_concurrent
        self._running_count = 0
        self._running_lock = asyncio.Lock()
        self._workers: list[asyncio.Task] = []
        self._process_callback: Optional[Callable] = None
        self._task_counter = 0

        # Stats
        self._total_processed = 0
        self._total_enqueued = 0

    def set_processor(self, callback: Callable):
        """Define a função que processa tarefas"""
        self._process_callback = callback

    async def enqueue(self, task: QueuedTask):
        """Adiciona tarefa à fila"""
        self._total_enqueued += 1
        await self._queue.put((task.priority, task))
        log.info("📋 Tarefa na fila",
                 task_id=task.task_id,
                 priority=task.priority.name,
                 queue_size=self._queue.qsize())

    async def start_workers(self, num_workers: int = 1):
        """Inicia workers para processar a fila"""
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
        log.info("🔧 Task queue workers iniciados", count=num_workers)

    async def _worker(self, worker_id: int):
        """Worker que processa tarefas da fila"""
        while True:
            try:
                priority, task = await self._queue.get()

                async with self._running_lock:
                    self._running_count += 1

                log.info("⚙️ Processando tarefa",
                         worker=worker_id,
                         task_id=task.task_id,
                         priority=task.priority.name)

                try:
                    if self._process_callback:
                        result = await self._process_callback(task)
                        
                        # Enviar resposta via callback
                        if task.callback and result:
                            await task.callback(result)

                    self._total_processed += 1

                except Exception as e:
                    log.error("❌ Erro processando tarefa",
                             task_id=task.task_id, error=str(e))

                finally:
                    async with self._running_lock:
                        self._running_count -= 1
                    self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("❌ Worker error", worker=worker_id, error=str(e))
                await asyncio.sleep(1)

    async def stop(self):
        """Para todos os workers"""
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        log.info("🔧 Task queue workers parados")

    def get_stats(self) -> dict:
        """Stats da fila"""
        return {
            "queue_size": self._queue.qsize(),
            "running": self._running_count,
            "total_enqueued": self._total_enqueued,
            "total_processed": self._total_processed,
        }
