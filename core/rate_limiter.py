"""
Open-PY — Rate Limiter (Token Bucket)
Protege contra flood no Telegram e controla throughput de agentes.

Especificações (baseadas na recomendação do Ori):
- 1 msg/s por chat
- 20 msg/s global
- Burst máximo: 5
- 429 com Retry-After + exponential backoff + jitter
- Deduplicação silenciosa em janela de 1s
"""

import asyncio
import hashlib
import time
from collections import defaultdict
from typing import Optional

from shared.logger import get_logger

log = get_logger("ratelimit")


class TokenBucket:
    """
    Token Bucket rate limiter.
    Tokens se recarregam a uma taxa fixa (rate).
    Permite bursts até max_tokens.
    """

    def __init__(self, rate: float = 1.0, max_tokens: int = 5):
        """
        Args:
            rate: Tokens por segundo
            max_tokens: Máximo de tokens acumulados (burst)
        """
        self.rate = rate
        self.max_tokens = max_tokens
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Tenta consumir tokens. Retorna True se permitido.
        """
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def wait_and_acquire(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """
        Espera até ter tokens disponíveis (com timeout).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.acquire(tokens):
                return True
            # Calcular tempo até próximo token
            wait_time = (tokens - self._tokens) / self.rate
            wait_time = min(wait_time, deadline - time.monotonic(), 1.0)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        return False

    def _refill(self):
        """Recarrega tokens baseado no tempo decorrido"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.max_tokens,
            self._tokens + elapsed * self.rate
        )
        self._last_refill = now

    @property
    def available(self) -> float:
        """Tokens disponíveis (sem lock, para monitoramento)"""
        self._refill()
        return self._tokens


class RateLimiter:
    """
    Rate limiter centralizado com:
    - Limites per-chat e global
    - Deduplicação de mensagens
    - Proteção contra flood
    """

    def __init__(
        self,
        per_chat_rate: float = 1.0,
        per_chat_burst: int = 5,
        global_rate: float = 20.0,
        global_burst: int = 30,
        dedup_window: float = 1.0,
    ):
        # Buckets per-chat
        self._chat_buckets: dict[int, TokenBucket] = defaultdict(
            lambda: TokenBucket(rate=per_chat_rate, max_tokens=per_chat_burst)
        )
        # Bucket global
        self._global_bucket = TokenBucket(rate=global_rate, max_tokens=global_burst)
        # Deduplicação
        self._dedup_window = dedup_window
        self._recent_hashes: dict[str, float] = {}  # hash -> timestamp
        self._dedup_lock = asyncio.Lock()
        # Stats
        self._stats = {
            "total_requests": 0,
            "allowed": 0,
            "rate_limited": 0,
            "deduplicated": 0,
        }

    async def check(self, chat_id: int, message_text: str = "") -> dict:
        """
        Verifica se uma mensagem deve ser processada.
        
        Returns:
            {
                "allowed": bool,
                "reason": str,  # "ok", "rate_limited", "duplicate", "global_limit"
                "retry_after": float  # segundos até poder enviar
            }
        """
        self._stats["total_requests"] += 1

        # 1. Deduplicação
        if message_text and await self._is_duplicate(chat_id, message_text):
            self._stats["deduplicated"] += 1
            return {
                "allowed": False,
                "reason": "duplicate",
                "retry_after": self._dedup_window,
            }

        # 2. Rate limit global
        if not await self._global_bucket.acquire():
            self._stats["rate_limited"] += 1
            retry = 1.0 / self._global_bucket.rate
            log.warning("⚠️ Rate limit global atingido")
            return {
                "allowed": False,
                "reason": "global_limit",
                "retry_after": retry,
            }

        # 3. Rate limit per-chat
        bucket = self._chat_buckets[chat_id]
        if not await bucket.acquire():
            self._stats["rate_limited"] += 1
            retry = 1.0 / bucket.rate
            log.warning("⚠️ Rate limit per-chat atingido", chat_id=chat_id)
            return {
                "allowed": False,
                "reason": "rate_limited",
                "retry_after": retry,
            }

        self._stats["allowed"] += 1
        return {"allowed": True, "reason": "ok", "retry_after": 0}

    async def _is_duplicate(self, chat_id: int, text: str) -> bool:
        """Detecta mensagens duplicadas em janela de tempo"""
        async with self._dedup_lock:
            # Hash da mensagem (chat_id + texto)
            msg_hash = hashlib.md5(
                f"{chat_id}:{text}".encode()
            ).hexdigest()[:12]

            now = time.monotonic()

            # Limpar hashes antigos
            expired = [
                h for h, ts in self._recent_hashes.items()
                if now - ts > self._dedup_window
            ]
            for h in expired:
                del self._recent_hashes[h]

            # Verificar duplicata
            if msg_hash in self._recent_hashes:
                return True

            # Registrar
            self._recent_hashes[msg_hash] = now
            return False

    def get_stats(self) -> dict:
        """Retorna estatísticas do rate limiter"""
        return {
            **self._stats,
            "global_tokens": round(self._global_bucket.available, 1),
            "active_chats": len(self._chat_buckets),
        }

    async def cleanup(self):
        """Limpa buckets de chats inativos (chamar periodicamente)"""
        # Remove buckets que não são usados há mais de 1 hora
        # (simplificado: limpa todos os buckets inativos)
        inactive = [
            cid for cid, bucket in self._chat_buckets.items()
            if bucket.available >= bucket.max_tokens  # bucket cheio = inativo
        ]
        for cid in inactive:
            del self._chat_buckets[cid]
        if inactive:
            log.info("🧹 Buckets inativos removidos", count=len(inactive))
