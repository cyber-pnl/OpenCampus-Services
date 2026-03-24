import os
from dotenv import load_dotenv

load_dotenv()

import asyncpg
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")  # Obligatoire : doit être défini dans .env

_pool: asyncpg.Pool | None = None


async def init_db():
    """Crée le pool de connexions et initialise le schéma si besoin."""
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    logger.info("Pool PostgreSQL initialisé")

    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                jti        UUID PRIMARY KEY,
                revoked_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL
            );

            -- Index pour accélérer la lookup par jti
            CREATE INDEX IF NOT EXISTS idx_revoked_tokens_jti
                ON revoked_tokens (jti);

            -- Nettoyage automatique des tokens expirés (pas bloquant)
            DELETE FROM revoked_tokens WHERE expires_at < NOW();
        """)
        logger.info("Schéma auth_db vérifié")


@asynccontextmanager
async def get_db():
    """Context manager pour obtenir une connexion depuis le pool."""
    if _pool is None:
        raise RuntimeError("Le pool de base de données n'est pas initialisé")
    async with _pool.acquire() as conn:
        yield conn
