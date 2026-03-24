# jwt_handler.py — Gestion des tokens JWT

import os
from dotenv import load_dotenv

load_dotenv()

import jwt
import uuid
import logging
from datetime import datetime, timedelta
from fastapi import HTTPException

logger = logging.getLogger(__name__)

JWT_SECRET    = os.getenv("JWT_SECRET")  # Obligatoire : doit être défini dans .env
JWT_ALGO      = "HS256"
JWT_EXP_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "8"))

# Store for revoked tokens (in production, use Redis or database)
_revoked_tokens: dict = {}


def create_token(uid: str, role: str, display_name: str) -> tuple[str, str, datetime]:
    """Crée un token JWT signé avec uid, rôle et JTI unique."""
    jti = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=JWT_EXP_HOURS)
    payload = {
        "jti":          jti,
        "uid":          uid,
        "role":         role,
        "display_name": display_name,
        "iat":          datetime.utcnow(),
        "exp":          expires_at,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return token, jti, expires_at


def decode_token(token: str) -> dict:
    """Décode et valide un token JWT. Lève une HTTPException si invalide."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expiré")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalide")


async def revoke_token(jti: str, exp: int) -> None:
    """Révoque un token JWT en ajoutant son JTI à la liste des tokens révoqués."""
    from datetime import datetime
    _revoked_tokens[jti] = {
        "revoked_at": datetime.utcnow(),
        "expires_at": datetime.utcfromtimestamp(exp),
    }
    logger.info(f"Token révoqué: {jti}")


async def is_token_revoked(jti: str) -> bool:
    """Vérifie si un token a été révoqué."""
    return jti in _revoked_tokens
