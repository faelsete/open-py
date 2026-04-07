import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost/openpy')
    try:
        # Check indices
        indices = await conn.fetch('''
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'memories';
        ''')
        for idx in indices:
            print(f"{idx['indexname']}: {idx['indexdef']}")
            
        print('--- RECREATING INDEX ---')
        await conn.execute('DROP INDEX IF EXISTS idx_memories_embedding;')
        # Using optimal hnsw params
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING hnsw(embedding vector_cosine_ops) WITH (m = 32, ef_construction = 128);')
        print('INDEX CREATED')
    except Exception as e:
        print('Error:', e)
    finally:
        await conn.close()

asyncio.run(main())
