"""
Open-PY — Memory Manager
3 camadas: Contexto (RAM) → memory.md (filesystem) → PostgreSQL (longo prazo)

Formato de I/O:
- Buffer (RAM):   list[dict] com {role, content, timestamp, tokens}
- Filesystem:     data/memory/daily/YYYY-MM-DD_NNN.md (markdown)
- PostgreSQL:     tabela 'memories' com id, content, source, tags[], embedding, created_at
- Preferências:   tabela 'memories' com tag 'preferência/*' e importance >= 7
"""

import os
import asyncio
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import aiofiles
import asyncpg

from shared.config import MemoryConfig
from shared.models import Memory, MemoryType
from shared.logger import get_logger

log = get_logger("memory")

# ============================================
# FORMATOS E CAMINHOS — Referência canônica
# ============================================

MEMORY_PATHS = {
    "daily_dir":    "data/memory/daily/",          # memory.md temporários
    "audit_dir":    "data/audit/",                  # audit trail (JSONL)
    "media_dir":    "data/media/",                  # photo/ audio/ video/ document/
    "soul":         "data/soul.md",                 # memória permanente
    "essence":      "data/essence.md",              # personalidade
    "versions":     "data/identity_versions/",      # backups de soul/essence
}

MEMORY_SCHEMA = {
    "buffer_entry": {
        "role": "str (user|assistant)",
        "content": "str",
        "timestamp": "ISO 8601",
        "tokens": "int (estimado)",
    },
    "md_file": {
        "format": "markdown",
        "naming": "YYYY-MM-DD_NNN.md",
        "content": "## User\\n{input}\\n\\n## Assistant\\n{response}",
    },
    "db_table": {
        "table": "memories",
        "columns": "id SERIAL, content TEXT, source TEXT, tags TEXT[], "
                   "embedding VECTOR(384), importance INT, created_at TIMESTAMP",
    },
}


class MemoryManager:
    """
    Gerenciador de memória em 3 camadas:

    Camada 1: Buffer em RAM (contexto vivo)
        → Salvo em memory.md quando atinge 128K tokens OU a cada 1h

    Camada 2: Arquivos memory.md (filesystem, temporários)
        → Vários por dia: data/memory/daily/2026-04-02_001.md
        → Migrados para PostgreSQL diariamente às 00:00

    Camada 3: PostgreSQL + pgvector (longo prazo, permanente)
        → Após migração: memory.md DESCARTADOS
    """

    def __init__(self, db_pool: Optional[asyncpg.Pool],
                 config: MemoryConfig, install_dir: str):
        self.db = db_pool
        self.config = config
        self.install_dir = install_dir
        self.daily_dir = Path(install_dir) / MEMORY_PATHS["daily_dir"]
        self.daily_dir.mkdir(parents=True, exist_ok=True)

        # Buffer de contexto (Camada 1)
        self._buffer: list[dict] = []
        self._buffer_tokens: int = 0
        self._last_save: datetime = datetime.now()
        self._file_counter: int = self._get_next_file_counter()

        # Embedder (carregado sob demanda)
        self._embedder = None

    def get_memory_layout(self) -> dict:
        """Retorna layout completo de memória para debug/observabilidade"""
        return {
            "paths": {k: str(Path(self.install_dir) / v) for k, v in MEMORY_PATHS.items()},
            "schema": MEMORY_SCHEMA,
            "buffer_size": len(self._buffer),
            "buffer_tokens": self._buffer_tokens,
            "md_files": len(list(self.daily_dir.glob("*.md"))),
        }

    # ============================================
    # CAMADA 1: BUFFER DE CONTEXTO
    # ============================================

    async def buffer_interaction(self, user_input: str, response: str):
        """Adiciona interação ao buffer de contexto"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user_input,
            "assistant": response,
        }
        self._buffer.append(entry)
        self._buffer_tokens += self._estimate_tokens(user_input + response)

        # Verificar se deve salvar
        should_save = (
            self._buffer_tokens >= self.config.context_max_tokens or
            self._minutes_since_last_save() >= self.config.context_save_interval_minutes
        )

        if should_save:
            await self._save_buffer_to_md()

    async def flush(self):
        """Força salvamento do buffer atual"""
        if self._buffer:
            await self._save_buffer_to_md()

    # ============================================
    # CAMADA 2: MEMORY.MD (FILESYSTEM)
    # ============================================

    async def _save_buffer_to_md(self):
        """Salva buffer atual como arquivo memory.md"""
        if not self._buffer:
            return

        today = date.today().isoformat()
        self._file_counter += 1
        filename = f"{today}_{self._file_counter:03d}.md"
        filepath = self.daily_dir / filename

        # Montar conteúdo do arquivo
        content = f"# Memory Snapshot — {datetime.now().isoformat()}\n\n"
        content += f"**Tokens estimados**: {self._buffer_tokens}\n"
        content += f"**Interações**: {len(self._buffer)}\n\n---\n\n"

        for entry in self._buffer:
            content += f"### [{entry['timestamp']}]\n"
            content += f"**User**: {entry['user']}\n\n"
            content += f"**Assistant**: {entry['assistant']}\n\n---\n\n"

        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(content)

        log.info("💾 Memory.md salvo", file=filename,
                 tokens=self._buffer_tokens, interactions=len(self._buffer))

        # Limpar buffer
        self._buffer.clear()
        self._buffer_tokens = 0
        self._last_save = datetime.now()

    # ============================================
    # CAMADA 3: MIGRAÇÃO PARA POSTGRESQL
    # ============================================

    async def migrate_daily(self):
        """
        Migração diária: memory.md → PostgreSQL → descarte md
        Chamada pelo scheduler às 00:00 (configurável)
        """
        if not self.db:
            log.warning("⚠️ Migração ignorada — sem banco de dados")
            return

        # Primeiro, salvar qualquer buffer pendente
        await self.flush()

        # Listar todos os .md do dia anterior e mais antigos
        md_files = sorted(self.daily_dir.glob("*.md"))
        today = date.today().isoformat()

        files_to_migrate = [f for f in md_files if not f.name.startswith(today)]

        if not files_to_migrate:
            log.info("Nenhum arquivo para migrar")
            return

        log.info(f"📦 Migrando {len(files_to_migrate)} arquivos para PostgreSQL")

        for filepath in files_to_migrate:
            try:
                async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                    content = await f.read()

                # Gerar embedding
                embedding = await self._get_embedding(content[:2000])

                # Extrair date do nome do arquivo
                file_date = filepath.stem.split("_")[0]

                # Auto-gerar tags
                tags = self._extract_tags(content)

                # Salvar no PostgreSQL
                await self.db.execute("""
                    INSERT INTO memories (content, content_type, source, tags,
                                          embedding, importance, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, content, "interaction", "core", tags, embedding, 5,
                     json.dumps({"source_file": filepath.name, "date": file_date}))

                # Descartar md após migração bem-sucedida
                if self.config.discard_md_after_migration:
                    os.remove(filepath)
                    log.info(f"🗑️ {filepath.name} migrado e descartado")
                else:
                    log.info(f"📦 {filepath.name} migrado (md mantido)")

            except Exception as e:
                log.error(f"❌ Erro migrando {filepath.name}", error=str(e))

        log.info("✅ Migração diária concluída")

    # ============================================
    # SAVE MEMORY (DIRETO NO POSTGRESQL)
    # ============================================

    async def save_memory(self, content: str, content_type: str = "fact",
                          source: str = "core", tags: list[str] = None,
                          importance: int = 5):
        """Salva uma memória diretamente no PostgreSQL"""
        if not self.db:
            log.warning("⚠️ Sem banco — memória não salva")
            return

        tags = tags or []
        embedding = await self._get_embedding(content)

        # Auto-tags
        auto_tags = self._extract_tags(content)
        all_tags = list(set(tags + auto_tags))

        await self.db.execute("""
            INSERT INTO memories (content, content_type, source, tags,
                                  embedding, importance)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, content, content_type, source, all_tags, embedding, importance)

        log.info("💾 Memória salva no PostgreSQL", type=content_type, tags=all_tags)

    # ============================================
    # BUSCA (4 MODOS)
    # ============================================

    async def search(self, query: str, mode: str = "hybrid",
                     limit: int = 10) -> list[dict]:
        """Busca memórias: tag | keyword | semantic | hybrid"""
        if not self.db:
            return []

        if mode == "tag":
            return await self._search_by_tag(query, limit)
        elif mode == "keyword":
            return await self._search_by_keyword(query, limit)
        elif mode == "semantic":
            return await self._search_semantic(query, limit)
        else:
            return await self._search_hybrid(query, limit)

    async def _search_by_tag(self, tag: str, limit: int) -> list[dict]:
        rows = await self.db.fetch("""
            SELECT id, content, tags, importance, created_at
            FROM memories WHERE $1 = ANY(tags)
            ORDER BY importance DESC, created_at DESC LIMIT $2
        """, tag, limit)
        return [dict(r) for r in rows]

    async def _search_by_keyword(self, keyword: str, limit: int) -> list[dict]:
        rows = await self.db.fetch("""
            SELECT id, content, tags, importance, created_at
            FROM memories WHERE content ILIKE '%' || $1 || '%'
            ORDER BY created_at DESC LIMIT $2
        """, keyword, limit)
        return [dict(r) for r in rows]

    async def _search_semantic(self, query: str, limit: int) -> list[dict]:
        embedding = await self._get_embedding(query)
        if embedding is None:
            return await self._search_by_keyword(query, limit)

        rows = await self.db.fetch("""
            SELECT id, content, tags, importance, created_at,
                   1 - (embedding <=> $1) AS similarity
            FROM memories WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1 LIMIT $2
        """, str(embedding), limit)
        return [dict(r) for r in rows]

    async def _search_hybrid(self, query: str, limit: int) -> list[dict]:
        embedding = await self._get_embedding(query)
        if embedding is None:
            return await self._search_by_keyword(query, limit)

        rows = await self.db.fetch("""
            SELECT id, content, tags, importance, created_at,
                   (1 - (embedding <=> $1)) AS similarity
            FROM memories
            WHERE content ILIKE '%' || $2 || '%'
               OR (embedding IS NOT NULL AND embedding <=> $1 < 0.7)
            ORDER BY similarity DESC NULLS LAST
            LIMIT $3
        """, str(embedding), query, limit)
        return [dict(r) for r in rows]

    # ============================================
    # STATS
    # ============================================

    async def get_stats(self) -> dict:
        """Estatísticas do sistema de memória"""
        result = {"total": 0, "today": 0, "unique_tags": 0,
                  "last_save": self._last_save.isoformat(),
                  "buffer_size": len(self._buffer),
                  "buffer_tokens": self._buffer_tokens,
                  "md_files": len(list(self.daily_dir.glob("*.md")))}

        if self.db:
            try:
                result["total"] = await self.db.fetchval(
                    "SELECT COUNT(*) FROM memories") or 0
                result["today"] = await self.db.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE created_at::date = CURRENT_DATE") or 0
                result["unique_tags"] = await self.db.fetchval(
                    "SELECT COUNT(DISTINCT unnest) FROM (SELECT unnest(tags) FROM memories) t") or 0
            except Exception:
                pass

        return result

    # ============================================
    # HELPERS
    # ============================================

    def _estimate_tokens(self, text: str) -> int:
        """Estimativa rápida: 1 token ≈ 4 caracteres"""
        return len(text) // 4

    def _minutes_since_last_save(self) -> float:
        return (datetime.now() - self._last_save).total_seconds() / 60

    def _get_next_file_counter(self) -> int:
        """Descobre o próximo número de arquivo para hoje"""
        today = date.today().isoformat()
        existing = list(self.daily_dir.glob(f"{today}_*.md"))
        if not existing:
            return 0
        numbers = []
        for f in existing:
            try:
                num = int(f.stem.split("_")[-1])
                numbers.append(num)
            except (ValueError, IndexError):
                pass
        return max(numbers) if numbers else 0

    def _extract_tags(self, content: str) -> list[str]:
        """Extrai tags básicas do conteúdo (sem LLM)"""
        tags = []
        content_lower = content.lower()
        # Tags por padrões
        tag_patterns = {
            "python": ["python", "pip", "venv", ".py"],
            "javascript": ["javascript", "node", "npm", ".js"],
            "código": ["código", "code", "script", "function", "def "],
            "erro": ["erro", "error", "bug", "traceback", "exception"],
            "telegram": ["telegram", "bot", "mensagem"],
            "api": ["api", "endpoint", "request", "response"],
            "banco": ["postgresql", "database", "sql", "query"],
            "decisão": ["decidiu", "decisão", "preferência", "prefiro"],
        }
        for tag, patterns in tag_patterns.items():
            if any(p in content_lower for p in patterns):
                tags.append(tag)
        return tags

    async def _get_embedding(self, text: str) -> Optional[list[float]]:
        """Gera embedding usando sentence-transformers (local, gratuito)"""
        try:
            if self._embedder is None:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self.config.embedding_model)
                log.info("✅ Modelo de embeddings carregado",
                         model=self.config.embedding_model)

            embedding = self._embedder.encode(text[:2000], convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            log.warning("⚠️ Erro gerando embedding", error=str(e))
            return None
