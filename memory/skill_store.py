"""
Open-PY v5.0 — Skill Store
Banco de habilidades aprendidas: o agente NUNCA erra a mesma coisa 2x.

Funcionalidade:
- Salva tarefas completadas com sucesso (hash + embedding + steps)
- Busca por similaridade semântica (pgvector) ou hash exato
- Incrementa contadores de sucesso/falha
- Cleanup de skills obsoletas

Tabela: skills (criada em migrations.py v5.0)
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

import asyncpg

from shared.config import SkillStoreConfig
from shared.logger import get_logger
from shared.models import Skill

log = get_logger("skills")


class SkillStore:
    """Banco de habilidades aprendidas pelo sistema."""

    def __init__(
        self,
        db_pool: Optional[asyncpg.Pool],
        config: SkillStoreConfig,
        memory_manager=None,  # Para embeddings
    ):
        self.db = db_pool
        self.config = config
        self.memory = memory_manager
        self._cache: dict[str, Skill] = {}  # hash → Skill (RAM cache)

    async def find_skill(self, task_description: str) -> Optional[Skill]:
        """
        Busca skill por similaridade.
        
        Estratégia:
        1. Hash exato (mais rápido)
        2. Busca semântica via pgvector (mais flexível)
        
        Retorna skill se success_count >= min_success_to_reuse.
        """
        if not self.db or not self.config.enabled:
            return None

        task_hash = self._compute_hash(task_description)

        # 1. Hash exato (cache RAM)
        if task_hash in self._cache:
            cached = self._cache[task_hash]
            if cached.success_count >= self.config.min_success_to_reuse:
                return cached

        # 2. Hash exato (PostgreSQL)
        try:
            row = await self.db.fetchrow(
                """SELECT id, task_hash, task_description, steps_json, tools_used,
                          success_count, failure_count, avg_duration_s, last_used, created_at
                   FROM skills WHERE task_hash = $1""",
                task_hash,
            )
            if row and row["success_count"] >= self.config.min_success_to_reuse:
                skill = self._row_to_skill(row)
                self._cache[task_hash] = skill
                return skill
        except Exception as e:
            log.warning("⚠️ Busca de skill por hash falhou", error=str(e))

        # 3. Busca semântica (se memory_manager tem embeddings)
        if self.memory and hasattr(self.memory, 'get_embedding'):
            try:
                embedding = await self.memory.get_embedding(task_description)
                if embedding:
                    row = await self.db.fetchrow(
                        """SELECT id, task_hash, task_description, steps_json, tools_used,
                                  success_count, failure_count, avg_duration_s, last_used, created_at
                           FROM skills
                           WHERE embedding IS NOT NULL
                             AND success_count >= $1
                           ORDER BY embedding <=> $2::vector
                           LIMIT 1""",
                        self.config.min_success_to_reuse,
                        str(embedding),
                    )
                    if row:
                        # Verificar threshold de similaridade
                        skill = self._row_to_skill(row)
                        self._cache[row["task_hash"]] = skill
                        return skill
            except Exception as e:
                log.warning("⚠️ Busca semântica de skill falhou", error=str(e))

        return None

    async def save_skill(
        self,
        task_description: str,
        task_hash: Optional[str] = None,
        tools_used: Optional[list[str]] = None,
        steps_json: Optional[list[dict]] = None,
        success: bool = True,
        duration_seconds: float = 0.0,
    ):
        """Salva ou atualiza skill no banco."""
        if not self.db or not self.config.enabled:
            return

        if not task_hash:
            task_hash = self._compute_hash(task_description)

        tools = tools_used or []
        steps = steps_json or []

        try:
            # Upsert: incrementa contadores se já existe
            await self.db.execute(
                """INSERT INTO skills (task_hash, task_description, steps_json, tools_used,
                                       success_count, failure_count, avg_duration_s, last_used)
                   VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, NOW())
                   ON CONFLICT (task_hash) DO UPDATE SET
                       success_count = CASE WHEN $8 THEN skills.success_count + 1 ELSE skills.success_count END,
                       failure_count = CASE WHEN NOT $8 THEN skills.failure_count + 1 ELSE skills.failure_count END,
                       avg_duration_s = (skills.avg_duration_s * skills.success_count + $7) / GREATEST(skills.success_count + 1, 1),
                       last_used = NOW(),
                       steps_json = CASE WHEN $8 AND $3::jsonb != '[]'::jsonb THEN $3::jsonb ELSE skills.steps_json END,
                       tools_used = CASE WHEN $8 AND cardinality($4) > 0 THEN $4 ELSE skills.tools_used END
                """,
                task_hash,
                task_description[:500],
                json.dumps(steps),
                tools,
                1 if success else 0,
                0 if success else 1,
                duration_seconds,
                success,
            )

            # Gerar embedding para busca semântica futura
            if self.memory and hasattr(self.memory, 'get_embedding'):
                try:
                    embedding = await self.memory.get_embedding(task_description)
                    if embedding:
                        await self.db.execute(
                            "UPDATE skills SET embedding = $1::vector WHERE task_hash = $2",
                            str(embedding),
                            task_hash,
                        )
                except Exception:
                    pass  # Embedding é nice-to-have, não bloqueia

            # Atualizar cache
            self._cache.pop(task_hash, None)

            log.info(
                "💾 Skill salva",
                task_hash=task_hash[:8],
                success=success,
                tools=len(tools),
            )

        except Exception as e:
            log.error("❌ Erro salvando skill", error=str(e))

    async def cleanup(self):
        """Remove skills obsoletas (0 sucessos após N dias, limite total)."""
        if not self.db or not self.config.enabled:
            return

        try:
            # 1. Remover skills com 0 sucessos após cleanup_days
            deleted = await self.db.execute(
                """DELETE FROM skills
                   WHERE success_count = 0
                     AND created_at < NOW() - INTERVAL '1 day' * $1""",
                self.config.cleanup_days,
            )
            log.info("🧹 Skills cleanup (sem sucesso)", deleted=deleted)

            # 2. Remover skills não usadas há max_skill_age_days
            deleted = await self.db.execute(
                """DELETE FROM skills
                   WHERE last_used < NOW() - INTERVAL '1 day' * $1""",
                self.config.max_skill_age_days,
            )
            log.info("🧹 Skills cleanup (obsoletas)", deleted=deleted)

            # 3. Limitar total de skills (manter as mais usadas)
            total = await self.db.fetchval("SELECT COUNT(*) FROM skills")
            if total and total > self.config.max_skills:
                overflow = total - self.config.max_skills
                await self.db.execute(
                    """DELETE FROM skills WHERE id IN (
                         SELECT id FROM skills
                         ORDER BY success_count ASC, last_used ASC
                         LIMIT $1
                       )""",
                    overflow,
                )
                log.info("🧹 Skills cleanup (overflow)", removed=overflow)

            # Limpar cache RAM
            self._cache.clear()

        except Exception as e:
            log.error("❌ Cleanup de skills falhou", error=str(e))

    async def get_stats(self) -> dict:
        """Estatísticas do skill store."""
        if not self.db:
            return {"status": "no_database"}

        try:
            total = await self.db.fetchval("SELECT COUNT(*) FROM skills") or 0
            reusable = await self.db.fetchval(
                "SELECT COUNT(*) FROM skills WHERE success_count >= $1",
                self.config.min_success_to_reuse,
            ) or 0
            top_skills = await self.db.fetch(
                """SELECT task_description, success_count, tools_used
                   FROM skills ORDER BY success_count DESC LIMIT 5"""
            )
            return {
                "total_skills": total,
                "reusable_skills": reusable,
                "cached": len(self._cache),
                "top_skills": [
                    {
                        "task": row["task_description"][:80],
                        "successes": row["success_count"],
                        "tools": row["tools_used"],
                    }
                    for row in top_skills
                ],
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _compute_hash(self, task: str) -> str:
        """Gera hash normalizado da tarefa."""
        normalized = task.lower().strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def _row_to_skill(self, row: asyncpg.Record) -> Skill:
        """Converte row do PostgreSQL para Skill."""
        steps = row["steps_json"]
        if isinstance(steps, str):
            steps = json.loads(steps)

        return Skill(
            id=row["id"],
            task_hash=row["task_hash"],
            task_description=row["task_description"],
            steps_json=steps if isinstance(steps, list) else [],
            tools_used=list(row["tools_used"]) if row["tools_used"] else [],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            avg_duration_seconds=row["avg_duration_s"] or 0.0,
            last_used=row["last_used"],
            created_at=row["created_at"],
        )
