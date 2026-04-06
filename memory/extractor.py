"""
Open-PY — Memory Extractor v3.0
Extração inteligente de memórias duráveis em background (fire-and-forget).

Inspirado em: Claude Code SessionMemory + extractMemories.
- Não bloqueia a resposta principal
- Usa thresholds de tokens + interações para decidir quando rodar
- Extrai apenas informações que devem sobreviver entre sessões
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Optional

from shared.models import ExtractionResult, MemoryType
from shared.config import MemoryConfig
from shared.logger import get_logger

log = get_logger("extractor")

EXTRACTION_PROMPT = """Você é um assistente de memória. Analise a conversa abaixo e extraia
APENAS informações que devem ser lembradas em conversas FUTURAS.

EXTRAIA:
- Preferências do usuário (como gosta de receber respostas, estilo, idioma)
- Decisões técnicas tomadas (frameworks escolhidos, arquitetura, padrões)
- Fatos sobre o projeto (nome, stack, objetivo, restrições)
- Correções de comportamento ("não faça X", "sempre faça Y")
- Informações pessoais relevantes (nome, papel, timezone)

NÃO EXTRAIA:
- Conteúdo efêmero (perguntas genéricas, small talk)
- Código fonte completo (apenas decisões sobre código)
- Informações deriváveis do contexto atual

CONVERSA:
{conversation}

Responda EXATAMENTE como um JSON array. Se não há nada relevante, retorne [].
Formato: [{{"content": "...", "type": "preference|decision|fact|feedback", "importance": 1-10, "tags": ["tag1"]}}]"""


class MemoryExtractor:
    """
    Extrai memórias duráveis em background.
    
    Padrão: fire-and-forget com thresholds inteligentes.
    Inspirado em Claude Code sessionMemory.ts shouldExtractMemory():
    - Token threshold (delta desde última extração)
    - Interaction threshold (número de tool calls / mensagens)
    """

    def __init__(self, config: MemoryConfig, llm_router=None, memory_manager=None):
        self.config = config
        self.llm = llm_router
        self.memory = memory_manager

        # Tracking
        self._last_extraction_tokens: int = 0
        self._interactions_since_extraction: int = 0
        self._running: bool = False
        self._total_extractions: int = 0
        self._total_memories_saved: int = 0

    def record_interaction(self, tokens: int = 0):
        """Registra uma interação processada"""
        self._interactions_since_extraction += 1

    def should_extract(self, current_tokens: int) -> bool:
        """
        Verifica se deve rodar extração agora.
        Dois thresholds (ambos devem ser atingidos):
        1. Delta de tokens desde última extração >= extraction_min_tokens
        2. Interações desde última extração >= extraction_min_interactions
        """
        if self._running:
            return False  # Já está rodando

        token_delta = current_tokens - self._last_extraction_tokens
        has_token_threshold = token_delta >= self.config.extraction_min_tokens
        has_interaction_threshold = (
            self._interactions_since_extraction >= self.config.extraction_min_interactions
        )

        return has_token_threshold and has_interaction_threshold

    async def maybe_extract(self, buffer: list[dict], current_tokens: int):
        """
        Verifica thresholds e extrai se necessário.
        Fire-and-forget: cria task que roda em background.
        """
        if not self.should_extract(current_tokens):
            return

        if not self.llm or not self.memory:
            return

        # Fire-and-forget
        asyncio.create_task(self._extract_safe(buffer.copy(), current_tokens))

    async def _extract_safe(self, buffer: list[dict], tokens_at_start: int):
        """Wrapper seguro para extração — nunca propaga exceções"""
        try:
            await self._extract(buffer, tokens_at_start)
        except Exception as e:
            log.error("❌ Extração de memórias falhou", error=str(e))

    async def _extract(self, buffer: list[dict], tokens_at_start: int) -> ExtractionResult:
        """Executa extração real de memórias"""
        self._running = True
        start = time.perf_counter()

        try:
            # Montar texto da conversa (últimas N interações)
            entries = buffer[-20:]  # Max 20 interações
            conversation_text = ""
            for i, entry in enumerate(entries):
                user = entry.get("user", "")
                assistant = entry.get("assistant", "")
                conversation_text += f"[{i+1}] User: {user}\nAssistant: {assistant}\n\n"

            if len(conversation_text) < 200:
                return ExtractionResult()  # Muito pouca conversa

            prompt = EXTRACTION_PROMPT.format(conversation=conversation_text[:6000])

            raw = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.2,
            )

            # Parse do resultado
            memories = self._parse_extraction(raw)

            # Salvar memórias extraídas
            saved = 0
            for mem in memories:
                try:
                    content = mem.get("content", "")
                    if not content or len(content) < 10:
                        continue

                    mem_type = mem.get("type", "fact")
                    importance = min(max(int(mem.get("importance", 5)), 1), 10)
                    tags = mem.get("tags", []) + ["auto-extracted"]

                    await self.memory.save_memory(
                        content=content,
                        content_type=mem_type,
                        source="extractor",
                        tags=tags,
                        importance=importance,
                    )
                    saved += 1
                except Exception as e:
                    log.warning("⚠️ Erro salvando memória extraída", error=str(e))

            duration_ms = (time.perf_counter() - start) * 1000

            # Atualizar tracking
            self._last_extraction_tokens = tokens_at_start
            self._interactions_since_extraction = 0
            self._total_extractions += 1
            self._total_memories_saved += saved

            log.info("🧠 Memórias extraídas em background",
                     total=len(memories), saved=saved,
                     duration_ms=round(duration_ms, 2))

            return ExtractionResult(
                extracted=saved,
                memories=memories,
                tokens_processed=tokens_at_start,
                duration_ms=round(duration_ms, 2),
            )

        finally:
            self._running = False

    def _parse_extraction(self, raw: str) -> list[dict]:
        """Parse robusto do JSON de memórias extraídas"""
        try:
            # Tentar extrair JSON array do markdown
            import re
            # Procurar por array JSON
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            log.debug("⚠️ Não conseguiu parsear extração, ignorando")
            return []

    def get_stats(self) -> dict:
        """Estatísticas do extrator"""
        return {
            "total_extractions": self._total_extractions,
            "total_memories_saved": self._total_memories_saved,
            "interactions_since_last": self._interactions_since_extraction,
            "last_extraction_tokens": self._last_extraction_tokens,
            "running": self._running,
        }
