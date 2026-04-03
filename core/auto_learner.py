"""
Open-PY — Auto-Learning System
Salva TUDO automaticamente e extrai preferências do usuário ao longo do tempo.

O que salva:
- Toda interação (pergunta + resposta)
- Preferências detectadas (gosta de X, prefere Y)
- Decisões tomadas
- Erros e como foram resolvidos
- Padrões de comportamento do usuário

Como aprende:
- Palavras-chave de preferência: "prefiro", "gosto de", "odeio", "sempre", "nunca"
- Padrões recorrentes: se o usuário pede a mesma coisa 3x, vira preferência
- Feedback direto: "boa resposta", "não gostei", "perfeito"
- Horários: quando o usuário costuma interagir
"""

import re
from datetime import datetime
from typing import Optional

from shared.logger import get_logger

log = get_logger("learning")

# Padrões para detectar preferências
PREFERENCE_PATTERNS = [
    # PT-BR
    (r'\b(prefiro|gosto de|amo|adoro|sempre uso|meu favorito)\b(.{5,80})', "positive"),
    (r'\b(odeio|detesto|nunca use|não gosto de|evite|pare de)\b(.{5,80})', "negative"),
    (r'\b(pode|usa|faça|faz|sempre|quero que)\b(.{5,80})', "directive"),
    # Feedback direto
    (r'\b(perfeito|ótimo|excelente|boa resposta|é isso|gostei)\b', "positive_feedback"),
    (r'\b(não gostei|ruim|errado|não é isso|refaça|tá errado)\b', "negative_feedback"),
]

# Categorias de aprendizado
LEARNING_CATEGORIES = {
    "estilo": ["linguagem", "formal", "informal", "emoji", "direto", "detalhado"],
    "tecnologia": ["python", "javascript", "typescript", "react", "django", "fastapi"],
    "comportamento": ["rápido", "detalhado", "código", "explicação", "pergunta"],
    "horário": [],  # Preenchido dinamicamente
}


class AutoLearner:
    """
    Aprende automaticamente com cada interação do usuário.
    Salva preferências, padrões e decisões no PostgreSQL.
    """

    def __init__(self, memory_manager=None, db_pool=None):
        self.memory = memory_manager
        self.db = db_pool
        self._preference_cache: dict[str, str] = {}
        self._interaction_count = 0

    async def learn_from_interaction(
        self,
        user_input: str,
        bot_response: str,
        user_id: int,
        input_type: str = "text",
    ):
        """
        Analisa uma interação e extrai aprendizados automaticamente.
        Chamado SEMPRE, após cada resposta do bot.
        """
        self._interaction_count += 1

        # 1. Salvar interação completa no buffer de memória
        if self.memory:
            await self.memory.buffer_interaction(user_input, bot_response)

        # 2. Extrair e salvar preferências
        preferences = self._extract_preferences(user_input)
        for pref in preferences:
            await self._save_preference(user_id, pref)

        # 3. Detectar feedback sobre resposta anterior
        feedback = self._detect_feedback(user_input)
        if feedback:
            await self._save_feedback(user_id, feedback, bot_response)

        # 4. Registrar padrão de horário
        await self._log_activity_pattern(user_id)

        # 5. A cada 10 interações, salvar resumo no PostgreSQL
        if self._interaction_count % 10 == 0 and self.memory:
            await self._save_interaction_summary(user_id)

    def _extract_preferences(self, text: str) -> list[dict]:
        """Extrai preferências do texto do usuário"""
        preferences = []
        text_lower = text.lower()

        for pattern, pref_type in PREFERENCE_PATTERNS:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                full_match = match.group(0)
                # Só salvar se tem conteúdo significativo
                if len(full_match) > 10:
                    preferences.append({
                        "type": pref_type,
                        "content": full_match.strip(),
                        "raw_text": text[:200],
                        "detected_at": datetime.now().isoformat(),
                    })

        return preferences

    def _detect_feedback(self, text: str) -> Optional[dict]:
        """Detecta feedback do usuário sobre resposta anterior"""
        text_lower = text.lower()

        # Feedback positivo
        positive = ["perfeito", "ótimo", "excelente", "boa", "gostei",
                     "é isso", "valeu", "obrigado", "show", "top"]
        # Feedback negativo
        negative = ["não gostei", "ruim", "errado", "não é isso",
                     "refaça", "tá errado", "isso não", "de novo"]

        for word in positive:
            if word in text_lower:
                return {"sentiment": "positive", "trigger": word}

        for word in negative:
            if word in text_lower:
                return {"sentiment": "negative", "trigger": word}

        return None

    async def _save_preference(self, user_id: int, preference: dict):
        """Salva preferência no PostgreSQL"""
        if not self.memory:
            return

        content = f"[PREFERÊNCIA] Usuário {user_id}: {preference['content']}"
        tags = ["preferência", preference["type"], "auto-aprendido"]

        # Importância maior para preferências explícitas
        importance = 8 if preference["type"] in ("positive", "negative") else 6

        await self.memory.save_memory(
            content=content,
            content_type="preference",
            source=f"user:{user_id}",
            tags=tags,
            importance=importance,
        )

        log.info("🧠 Preferência aprendida",
                 type=preference["type"],
                 content=preference["content"][:50])

    async def _save_feedback(self, user_id: int, feedback: dict, context: str):
        """Salva feedback do usuário sobre resposta"""
        if not self.memory:
            return

        content = (
            f"[FEEDBACK {feedback['sentiment'].upper()}] "
            f"Usuário reagiu com '{feedback['trigger']}' "
            f"ao contexto: {context[:200]}"
        )

        await self.memory.save_memory(
            content=content,
            content_type="decision",
            source=f"user:{user_id}",
            tags=["feedback", feedback["sentiment"], "auto-aprendido"],
            importance=7,
        )

        log.info("📝 Feedback registrado",
                 sentiment=feedback["sentiment"],
                 trigger=feedback["trigger"])

    async def _log_activity_pattern(self, user_id: int):
        """Registra padrão de atividade do usuário"""
        # Salvar horários de interação para aprender quando o usuário costuma usar
        # (não salvar cada uma, só a cada 50 interações ter um resumo)
        pass  # Simplificado por enquanto

    async def _save_interaction_summary(self, user_id: int):
        """A cada N interações, salva um resumo consolidado"""
        if not self.memory:
            return

        content = (
            f"[RESUMO] {self._interaction_count} interações totais com usuário {user_id}. "
            f"Sessão ativa desde o início. "
            f"Preferências acumuladas no banco de dados."
        )

        await self.memory.save_memory(
            content=content,
            content_type="interaction",
            source=f"system",
            tags=["resumo", "auto-aprendido", "sessão"],
            importance=4,
        )

    async def get_user_context(self, user_id: int, query: str = "") -> str:
        """
        Monta contexto personalizado do usuário para injetar no prompt.
        Busca preferências e memórias relevantes.
        """
        if not self.memory:
            return ""

        context_parts = []

        # 1. Buscar preferências do usuário
        preferences = await self.memory.search(
            f"PREFERÊNCIA user:{user_id}",
            mode="keyword",
            limit=10
        )
        if preferences:
            context_parts.append("## Preferências do usuário")
            for pref in preferences:
                content = pref.get("content", "")
                # Remover prefixo "[PREFERÊNCIA]"
                clean = content.replace(f"[PREFERÊNCIA] Usuário {user_id}: ", "")
                context_parts.append(f"- {clean[:100]}")

        # 2. Buscar memórias relevantes ao query atual
        if query:
            relevant = await self.memory.search(query, mode="hybrid", limit=5)
            if relevant:
                context_parts.append("\n## Memórias relevantes")
                for mem in relevant:
                    content = mem.get("content", "")[:150]
                    context_parts.append(f"- {content}")

        # 3. Buscar feedback recente
        feedback = await self.memory.search(
            f"FEEDBACK user:{user_id}",
            mode="keyword",
            limit=5
        )
        if feedback:
            context_parts.append("\n## Feedback recente do usuário")
            for fb in feedback:
                content = fb.get("content", "")[:100]
                context_parts.append(f"- {content}")

        return "\n".join(context_parts)
