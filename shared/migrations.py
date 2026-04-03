"""
Open-PY — Database Migrations
Cria todas as tabelas, extensões e índices no PostgreSQL.
"""

import asyncpg
from shared.logger import get_logger

log = get_logger("migrations")

SCHEMA_SQL = """
-- ============================================
-- EXTENSÕES
-- ============================================
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- TABELA: MEMÓRIAS DE LONGO PRAZO
-- ============================================
CREATE TABLE IF NOT EXISTS memories (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content         TEXT NOT NULL,
    content_type    VARCHAR(20) NOT NULL DEFAULT 'fact',
    source          VARCHAR(50) NOT NULL DEFAULT 'core',
    tags            TEXT[] NOT NULL DEFAULT '{}',
    embedding       vector(384),
    metadata        JSONB DEFAULT '{}',
    importance      SMALLINT DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
    access_count    INTEGER DEFAULT 0,
    last_accessed   TIMESTAMPTZ
);

-- ============================================
-- TABELA: COMPILAÇÕES DIÁRIAS
-- ============================================
CREATE TABLE IF NOT EXISTS daily_compilations (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary         TEXT NOT NULL,
    summary_embedding vector(384),
    memory_ids      BIGINT[] NOT NULL DEFAULT '{}',
    memory_count    INTEGER NOT NULL DEFAULT 0,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    highlights      JSONB DEFAULT '[]',
    decisions       JSONB DEFAULT '[]',
    open_tasks      JSONB DEFAULT '[]'
);

-- ============================================
-- TABELA: TAREFAS
-- ============================================
CREATE TABLE IF NOT EXISTS tasks (
    id              VARCHAR(20) PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    title           VARCHAR(200) NOT NULL,
    description     TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    agent_id        VARCHAR(50),
    result          TEXT,
    error           TEXT,
    priority        SMALLINT DEFAULT 5,
    tags            TEXT[] DEFAULT '{}'
);

-- ============================================
-- TABELA: LOGS DE AGENTES
-- ============================================
CREATE TABLE IF NOT EXISTS agent_logs (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id        VARCHAR(50) NOT NULL,
    task_id         VARCHAR(20),
    level           VARCHAR(10) NOT NULL DEFAULT 'info',
    message         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}'
);

-- ============================================
-- TABELA: CONFIGURAÇÃO DE AGENTES
-- ============================================
CREATE TABLE IF NOT EXISTS agent_configs (
    agent_id        VARCHAR(50) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    agent_type      VARCHAR(20) NOT NULL DEFAULT 'temporary',
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active     TIMESTAMPTZ,
    status          VARCHAR(20) DEFAULT 'stopped'
);

-- ============================================
-- TABELA: CRON JOBS
-- ============================================
CREATE TABLE IF NOT EXISTS cron_jobs (
    job_id          VARCHAR(50) PRIMARY KEY,
    cron_expr       VARCHAR(50) NOT NULL,
    agent_id        VARCHAR(50) NOT NULL,
    task            TEXT NOT NULL,
    enabled         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_run        TIMESTAMPTZ,
    next_run        TIMESTAMPTZ
);

-- ============================================
-- ÍNDICES DE PERFORMANCE
-- ============================================
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_content_trgm ON memories USING gin(content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(content_type);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);

CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_compilations(date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_tags ON daily_compilations USING GIN(tags);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_logs_agent ON agent_logs(agent_id, created_at DESC);
"""


async def run_migrations(dsn: str):
    """Executa as migrations no banco de dados"""
    log.info("Executando migrations...")

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(SCHEMA_SQL)
        log.info("✅ Migrations executadas com sucesso")
    except Exception as e:
        log.error("❌ Erro nas migrations", error=str(e))
        raise
    finally:
        await conn.close()


async def check_tables(dsn: str) -> dict[str, bool]:
    """Verifica quais tabelas existem"""
    conn = await asyncpg.connect(dsn)
    try:
        tables = await conn.fetch("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
        """)
        existing = {r['tablename'] for r in tables}
        required = {'memories', 'daily_compilations', 'tasks', 'agent_logs',
                     'agent_configs', 'cron_jobs'}
        return {t: t in existing for t in required}
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio
    from shared.config import load_config

    config = load_config()
    asyncio.run(run_migrations(config.database.dsn))
