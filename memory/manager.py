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
                   "embedding VECTOR, importance INT, created_at TIMESTAMP",
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
                 config: MemoryConfig, install_dir: str,
                 ollama_config=None):
        self.db = db_pool
        self.config = config
        self.install_dir = install_dir
        self.daily_dir = Path(install_dir) / MEMORY_PATHS["daily_dir"]
        self.daily_dir.mkdir(parents=True, exist_ok=True)

        # Buffer de contexto (Camada 1)
        self._buffer: list[dict] = []
        self._buffer_tokens: int = 0
        self._last_save: datetime = datetime.now()
        
        # Controle de Hora Solar e Recuperação de RAM Backup (Fases 3 e 4)
        self._current_hour: int = datetime.now().hour
        self._load_current_hour_md()

        # Embedder (carregado sob demanda)
        self._embedder = None
        
        # LLM Router injetado para sumarização de memória
        self.llm_router = None

        # v3.0: Ollama config para embeddings
        self._ollama_config = ollama_config
        self._use_ollama: bool = False
        if ollama_config and ollama_config.should_enable():
            self._use_ollama = True
            log.info("🦙 Ollama ativado para embeddings",
                     model=ollama_config.embedding_model,
                     url=ollama_config.url)

        # v3.0: Circuit breaker para compactação
        self._compact_failures: int = 0
        self._max_compact_failures: int = 3

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
        """Adiciona interação ao buffer de contexto + salva direto no PostgreSQL"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user_input,
            "assistant": response,
        }
        self._buffer.append(entry)
        self._buffer_tokens += self._estimate_tokens(user_input + response)

        # === SALVAR DIRETO NO POSTGRESQL (cada interação) ===
        # Isso garante que NADA se perde, mesmo com crash
        if self.db:
            try:
                content = f"User: {user_input}\n\nAssistant: {response}"
                tags = self._extract_tags(content)
                embedding = await self._get_embedding(content[:2000])

                await self.db.execute("""
                    INSERT INTO memories (content, content_type, source, tags,
                                          embedding, importance, metadata)
                    VALUES ($1, $2, $3, $4, $5::vector, $6, $7)
                """, content, "interaction", "core", tags, self._format_embedding(embedding), 5,
                     json.dumps({"type": "realtime", "ts": entry["timestamp"]}))

                log.debug("💾 Interação salva no PostgreSQL em tempo real")
            except Exception as e:
                log.warning("⚠️ Erro salvando interação no PostgreSQL", error=str(e))

        now = datetime.now()
        hour_changed = now.hour != self._current_hour

        # === v3.0: COMPACTAÇÃO INTELIGENTE (% da context window) ===
        usage_pct = self._buffer_tokens / max(self.config.context_max_tokens, 1)
        if usage_pct >= self.config.compact_threshold_pct:
            asyncio.create_task(self.compact_buffer())
        elif (usage_pct >= self.config.compact_light_pct and
              len(self._buffer) >= self.config.compact_light_min_entries):
            asyncio.create_task(self.compact_buffer(light=True))

        # Verificar se deve fazer backup intermediário do buffer
        should_sync = (
            len(self._buffer) > 0 and len(self._buffer) % 5 == 0 or
            self._buffer_tokens >= self.config.context_max_tokens or
            self._minutes_since_last_save() >= 15
        )

        if hour_changed:
            await self._save_buffer_to_md(clear_buffer=True)
            self._current_hour = now.hour
        elif should_sync:
            await self._save_buffer_to_md(clear_buffer=False)

    async def compact_buffer(self, light: bool = False):
        """
        v3.0: Smart Context Compaction com circuit breaker.
        light=False: compactação completa (resume 75% mais antigas)
        light=True:  compactação leve (resume 50% mais antigas)
        """
        # Circuit breaker check
        if self._compact_failures >= self._max_compact_failures:
            log.warning("🔴 Compactação desabilitada (circuit breaker)")
            return

        if not getattr(self, 'llm_router', None):
            return

        if len(self._buffer) < 5:
            return

        split_pct = 0.50 if light else 0.75
        split_idx = int(len(self._buffer) * split_pct)
        old_entries = self._buffer[:split_idx]
        recent_entries = self._buffer[split_idx:]

        mode = "leve" if light else "completa"
        log.info(f"🗜️ Compactação {mode}...",
                 size=len(self._buffer), compact=len(old_entries))

        try:
            text_to_summarize = "Resuma o seguinte trecho da conversa mantendo fatos importantes, contexto técnico e decisões:\n\n"
            for i, entry in enumerate(old_entries):
                text_to_summarize += f"[{i+1}] User: {entry['user']}\nAssistant: {entry['assistant']}\n\n"

            summary = await self.llm_router.complete(
                messages=[{"role": "user", "content": text_to_summarize}],
                max_tokens=400 if not light else 200,
                temperature=0.3
            )

            summarized_entry = {
                "timestamp": datetime.now().isoformat(),
                "user": "[CONTEXTO COMPACTADO]",
                "assistant": f"[Resumo de {len(old_entries)} mensagens]: {summary.strip()}"
            }

            self._buffer = [summarized_entry] + recent_entries
            self._buffer_tokens = sum(
                self._estimate_tokens(e['user'] + e['assistant']) for e in self._buffer
            )

            # Circuit breaker: reset no sucesso
            self._compact_failures = 0

            log.info(f"✅ Compactação {mode} concluída!",
                     original=len(old_entries) + len(recent_entries),
                     novo=len(self._buffer))
        except Exception as e:
            self._compact_failures += 1
            if self._compact_failures >= self._max_compact_failures:
                log.error("🔴 Circuit breaker: compactação desabilitada após falhas",
                         failures=self._compact_failures)
            else:
                log.error("❌ Erro ao compactar buffer", error=str(e))

    async def flush(self):
        """Força salvamento do buffer atual"""
        if self._buffer:
            await self._save_buffer_to_md(clear_buffer=True)

    # ============================================
    # CAMADA 2: MEMORY.MD (FILESYSTEM)
    # ============================================

    async def _save_buffer_to_md(self, clear_buffer: bool = True):
        """Salva buffer atual como arquivo memory.md usando a Hora Solar"""
        if not self._buffer:
            return

        today = date.today().isoformat()
        current_hour = f"{self._current_hour:02d}00"
        filename = f"{today}_{current_hour}.md"
        filepath = self.daily_dir / filename

        # Montar conteúdo do arquivo com base em todo o buffer!
        content = f"# Memory Snapshot — {today} {current_hour}\n\n"
        content += f"**Tokens estimados**: {self._buffer_tokens}\n"
        content += f"**Interações**: {len(self._buffer)}\n\n---\n\n"

        for entry in self._buffer:
            content += f"### [{entry['timestamp']}]\n"
            content += f"**User**: {entry['user']}\n\n"
            content += f"**Assistant**: {entry['assistant']}\n\n---\n\n"

        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(content)

        log.info("💾 Memory.md sincronizado", file=filename,
                 tokens=self._buffer_tokens, interactions=len(self._buffer), clear=clear_buffer)

        # Limpar buffer somente na virada da hora
        if clear_buffer:
            self._buffer.clear()
            self._buffer_tokens = 0
            
        self._last_save = datetime.now()

    # ============================================
    # CAMADA 3: MIGRAÇÃO PARA POSTGRESQL
    # ============================================

    async def migrate_daily(self):
        """
        Migração diária: memory.md → PostgreSQL → descarte md
        Compila TODOS os .md do dia anterior em UM ÚNICO INSERT no DB.
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

        log.info(f"📦 Compilando {len(files_to_migrate)} arquivos para migração")

        # Agrupar arquivos por data (YYYY-MM-DD)
        files_by_date = {}
        for f in files_to_migrate:
            file_date = f.stem.split("_")[0]
            if file_date not in files_by_date:
                files_by_date[file_date] = []
            files_by_date[file_date].append(f)

        for date_str, date_files in files_by_date.items():
            compiled_content = ""
            all_tags = set()
            
            try:
                for filepath in sorted(date_files):
                    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                        content = await f.read()
                        compiled_content += f"\n\n=== {filepath.name} ===\n\n{content}"
                        all_tags.update(self._extract_tags(content))

                # Gerar embedding limitando aos primeiros 2000 chars da string compilada
                embedding = await self._get_embedding(compiled_content[:2000])

                # Salvar no PostgreSQL em um único INSERT para o dia inteiro
                await self.db.execute("""
                    INSERT INTO memories (content, content_type, source, tags,
                                          embedding, importance, metadata)
                    VALUES ($1, $2, $3, $4, $5::vector, $6, $7)
                """, compiled_content, "daily_compilation", "core", list(all_tags), self._format_embedding(embedding), 6,
                     json.dumps({"source_files_count": len(date_files), "date": date_str}))

                # Descartar md após migração bem-sucedida do dia
                if self.config.discard_md_after_migration:
                    for filepath in date_files:
                        os.remove(filepath)
                    log.info(f"🗑️ Buffer do dia {date_str} ({len(date_files)} arquivos) migrado e descartado")
                else:
                    log.info(f"📦 Buffer do dia {date_str} ({len(date_files)} arquivos) migrado (md mantido)")

            except Exception as e:
                log.error(f"❌ Erro migrando buffer do dia {date_str}", error=str(e))

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

        try:
            tags = tags or []
            embedding = await self._get_embedding(content)

            # Auto-tags
            auto_tags = self._extract_tags(content)
            all_tags = list(set(tags + auto_tags))

            await self.db.execute("""
                INSERT INTO memories (content, content_type, source, tags,
                                      embedding, importance)
                VALUES ($1, $2, $3, $4, $5::vector, $6)
            """, content, content_type, source, all_tags, self._format_embedding(embedding), importance)

            log.info("💾 Memória salva no PostgreSQL", type=content_type, tags=all_tags)
        except Exception as e:
            log.warning("⚠️ Erro salvando memória no PostgreSQL", error=str(e))

    # ============================================
    # BUSCA NO BUFFER (RAM) — Curto prazo
    # ============================================

    def search_buffer(self, query: str, limit: int = 5) -> list[dict]:
        """Busca keyword simples no buffer RAM"""
        query_lower = query.lower()
        results = []
        for entry in reversed(self._buffer):  # Mais recentes primeiro
            combined = f"{entry.get('user', '')} {entry.get('assistant', '')}".lower()
            if query_lower in combined:
                results.append({
                    "content": f"User: {entry['user']}\nAssistant: {entry['assistant']}",
                    "tags": ["buffer", "recent"],
                    "importance": 7,  # Recente = mais importante
                    "created_at": entry.get("timestamp", ""),
                })
                if len(results) >= limit:
                    break
        return results

    def get_recent_buffer(self, limit: int = 5) -> list[dict]:
        """Retorna as N interações mais recentes do buffer"""
        recent = self._buffer[-limit:] if self._buffer else []
        return [
            {
                "content": f"User: {e['user']}\nAssistant: {e['assistant']}",
                "tags": ["buffer", "recent"],
                "importance": 7,
                "created_at": e.get("timestamp", ""),
            }
            for e in reversed(recent)
        ]

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
                   1 - (embedding <=> $1::vector) AS similarity
            FROM memories WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector LIMIT $2
        """, self._format_embedding(embedding), limit)
        return [dict(r) for r in rows]

    async def _search_hybrid(self, query: str, limit: int) -> list[dict]:
        embedding = await self._get_embedding(query)
        if embedding is None:
            return await self._search_by_keyword(query, limit)

        rows = await self.db.fetch("""
            SELECT id, content, tags, importance, created_at,
                   (1 - (embedding <=> $1::vector)) AS similarity
            FROM memories
            WHERE content ILIKE '%' || $2 || '%'
               OR (embedding IS NOT NULL AND embedding <=> $1::vector < 0.7)
            ORDER BY similarity DESC NULLS LAST
            LIMIT $3
        """, self._format_embedding(embedding), query, limit)
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

    def _format_embedding(self, emb: list[float]) -> Optional[str]:
        """Converte list[float] para string '[0.1, 0.2, ...]' compatível com pgvector"""
        if emb is None:
            return None
        return '[' + ','.join(str(x) for x in emb) + ']'

    def _estimate_tokens(self, text: str) -> int:
        """Estimativa rápida: 1 token ≈ 4 caracteres"""
        return len(text) // 4

    def _minutes_since_last_save(self) -> float:
        return (datetime.now() - self._last_save).total_seconds() / 60

    def _load_current_hour_md(self):
        """
        No startup do bot, tenta recuperar o _buffer a partir do arquivo MD 
        da hora solar atual se existir. Evita amnésia imediata em restarts.
        """
        import re
        today = date.today().isoformat()
        current_hour = f"{self._current_hour:02d}00"
        filename = f"{today}_{current_hour}.md"
        filepath = self.daily_dir / filename
        
        if not filepath.exists():
            return
            
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                
            entries = content.split("### [")
            for entry_block in entries[1:]:
                lines = entry_block.split("\n", 1)
                if not lines:
                    continue
                timestamp = lines[0].strip().replace("]", "")
                rest = lines[1] if len(lines) > 1 else ""
                
                user_match = re.search(r"\*\*User\*\*:\s*(.*?)\n\n\*\*Assistant\*\*", rest, re.DOTALL)
                asst_match = re.search(r"\*\*Assistant\*\*:\s*(.*?)\n\n---", rest, re.DOTALL)
                
                if user_match and asst_match:
                    user_text = user_match.group(1).strip()
                    asst_text = asst_match.group(1).strip()
                    self._buffer.append({
                        "timestamp": timestamp,
                        "user": user_text,
                        "assistant": asst_text
                    })
                    self._buffer_tokens += self._estimate_tokens(user_text + asst_text)
                    
            if self._buffer:
                log.info("♻️ Memória da hora solar restaurada", filename=filename, interactions=len(self._buffer))
                
        except Exception as e:
            log.error("⚠️ Fallback: erro ao restaurar memória .md na inicialização", error=str(e))

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
        """
        v4.1: Gera embedding via Ollama (CPU/GPU) ou sentence-transformers (CPU fallback).
        Ollama: bge-m3 (1024 dims, multilingual) — padrão quando RAM >= 4GB
        Fallback: all-MiniLM-L6-v2 (384 dims, CPU)
        """
        # === CAMINHO 1: Ollama (se disponível e habilitado) ===
        if self._use_ollama and self._ollama_config:
            try:
                import aiohttp
                timeout = aiohttp.ClientTimeout(total=self._ollama_config.request_timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    resp = await session.post(
                        f"{self._ollama_config.url}/api/embeddings",
                        json={
                            "model": self._ollama_config.embedding_model,
                            "prompt": text[:8192]  # nomic-embed-text suporta 8192 tokens
                        }
                    )
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("embedding")
                    else:
                        log.warning("⚠️ Ollama retornou status", status=resp.status)
                        # Fallback para sentence-transformers
            except Exception as e:
                log.warning("⚠️ Ollama indisponível, fallback para CPU", error=str(e))
                # Desabilitar Ollama temporariamente para evitar spam de erros
                self._use_ollama = False

        # === CAMINHO 2: sentence-transformers (CPU fallback) ===
        try:
            if self._embedder is None:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self.config.embedding_model)
                log.info("✅ Modelo de embeddings carregado (CPU fallback)",
                         model=self.config.embedding_model)

            embedding = self._embedder.encode(text[:2000], convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            log.warning("⚠️ Erro gerando embedding", error=str(e))
            return None
