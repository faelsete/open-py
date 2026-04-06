"""
Open-PY — Feedback Loop v3.0
Auto-ajuste do Core baseado em padrões de uso.

Inspirado em: Claude Code memdir.ts (typed memory taxonomy) +
extractMemories.ts (background analysis).

Analisa periodicamente:
- Padrões de rejeição do validator
- Tipos de input mais frequentes
- Agentes com mais fallbacks
- Preferências implícitas do usuário
"""

import asyncio
import json
from datetime import datetime
from typing import Optional
from collections import defaultdict

from shared.models import MemoryType
from shared.logger import get_logger

log = get_logger("feedback")

ANALYSIS_PROMPT = """Analise estas interações recentes e identifique:
1. Padrões de comportamento do usuário (como ele pede coisas, preferências implícitas)
2. Áreas onde o bot pode melhorar (respostas lentas, erros recorrentes, mal-entendidos)
3. Ajustes sugeridos para o sistema (routing, modelos, tom de resposta)

Interações:
{interactions}

Métricas:
{metrics}

Responda como JSON array:
[{{"insight": "...", "category": "routing|tone|performance|user_pref|security", "importance": 1-10, "action": "sugestão de ação concreta"}}]

Se não há insights relevantes, retorne []."""


class FeedbackLoop:
    """
    Auto-ajuste do Core baseado em padrões de uso.
    
    Roda em background após N interações ou periodicamente.
    Salva insights como memórias de tipo "feedback" que influenciam
    conversas futuras via busca semântica.
    """

    def __init__(self, llm_router=None, memory_manager=None,
                 pipeline=None, orchestrator=None, validator=None):
        self.llm = llm_router
        self.memory = memory_manager
        self.pipeline = pipeline
        self.orchestrator = orchestrator
        self.validator = validator

        # Tracking de interações para análise
        self._interaction_log: list[dict] = []
        self._max_log_size = 50
        self._analysis_interval = 25  # Analisar a cada N interações

        # Métricas acumuladas
        self._rejection_patterns: dict[str, int] = defaultdict(int)
        self._input_type_counts: dict[str, int] = defaultdict(int)
        self._agent_usage: dict[str, int] = defaultdict(int)
        self._total_analyses = 0

    def record_interaction(self, user_input: str, response: str,
                           input_type: str = "unknown",
                           delegated_to: str = None,
                           validated: bool = True,
                           duration_ms: float = 0):
        """Registra interação para análise futura"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "input_preview": user_input[:200],
            "response_preview": response[:200],
            "input_type": input_type,
            "delegated_to": delegated_to,
            "validated": validated,
            "duration_ms": round(duration_ms, 2),
        }
        self._interaction_log.append(entry)
        if len(self._interaction_log) > self._max_log_size:
            self._interaction_log = self._interaction_log[-self._max_log_size:]

        # Atualizar métricas
        self._input_type_counts[input_type] += 1
        if delegated_to:
            self._agent_usage[delegated_to] += 1
        if not validated:
            self._rejection_patterns[input_type] += 1

    def should_analyze(self) -> bool:
        """Verifica se deve rodar análise agora"""
        return len(self._interaction_log) >= self._analysis_interval

    async def maybe_analyze(self):
        """Roda análise se threshold atingido (fire-and-forget)"""
        if not self.should_analyze():
            return
        if not self.llm or not self.memory:
            return
        asyncio.create_task(self._analyze_safe())

    async def _analyze_safe(self):
        """Wrapper seguro para análise"""
        try:
            await self._analyze()
        except Exception as e:
            log.error("❌ Análise de feedback falhou", error=str(e))

    async def _analyze(self):
        """Executa análise de padrões e salva insights"""
        log.info("🔄 Iniciando análise de feedback...",
                 interactions=len(self._interaction_log))

        # Coletar métricas
        metrics = self._collect_metrics()

        # Montar texto das interações
        interactions_text = json.dumps(
            self._interaction_log[-15:],  # Últimas 15
            ensure_ascii=False, indent=2
        )

        prompt = ANALYSIS_PROMPT.format(
            interactions=interactions_text[:4000],
            metrics=json.dumps(metrics, ensure_ascii=False, indent=2),
        )

        raw = await self.llm.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
        )

        # Parse de insights
        insights = self._parse_insights(raw)
        saved = 0

        for insight in insights:
            try:
                content = insight.get("insight", "")
                if not content or len(content) < 10:
                    continue

                category = insight.get("category", "general")
                importance = min(max(int(insight.get("importance", 5)), 1), 10)
                action = insight.get("action", "")

                full_content = f"[FEEDBACK] {content}"
                if action:
                    full_content += f"\n[AÇÃO] {action}"

                await self.memory.save_memory(
                    content=full_content,
                    content_type="feedback",
                    source="feedback_loop",
                    tags=["auto-feedback", category],
                    importance=importance,
                )
                saved += 1
            except Exception as e:
                log.warning("⚠️ Erro salvando insight", error=str(e))

        self._total_analyses += 1

        # Reset do log (manter últimas 5 para continuidade)
        self._interaction_log = self._interaction_log[-5:]

        log.info("✅ Análise de feedback concluída",
                 insights_total=len(insights), saved=saved)

    def _collect_metrics(self) -> dict:
        """Coleta métricas atuais para a análise"""
        metrics = {
            "input_types": dict(self._input_type_counts),
            "agent_usage": dict(self._agent_usage),
            "rejection_patterns": dict(self._rejection_patterns),
        }

        # Pipeline metrics
        if self.pipeline:
            metrics["pipeline"] = self.pipeline.get_metrics()

        # Orchestrator fallback stats
        if self.orchestrator:
            metrics["fallbacks"] = self.orchestrator.get_fallback_stats()

        # Validator stats
        if self.validator:
            metrics["validator"] = self.validator.get_stats()

        return metrics

    def _parse_insights(self, raw: str) -> list[dict]:
        """Parse robusto do JSON de insights"""
        try:
            import re
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            log.debug("⚠️ Não conseguiu parsear insights")
            return []

    def get_stats(self) -> dict:
        """Estatísticas do feedback loop"""
        return {
            "total_analyses": self._total_analyses,
            "pending_interactions": len(self._interaction_log),
            "input_type_distribution": dict(self._input_type_counts),
            "top_agents": dict(sorted(
                self._agent_usage.items(),
                key=lambda x: x[1], reverse=True
            )[:5]),
        }
