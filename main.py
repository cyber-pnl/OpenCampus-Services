from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

from schemas import LoginRequest, LoginResponse, TokenVerifyResponse
from ldap_client import LDAPClient, LDAPConnectionError, LDAPInvalidCredentials
from jwt_handler import create_token, decode_token, revoke_token, is_token_revoked
from database import init_db

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
LOG_SERVICE_URL = os.getenv("LOG_SERVICE_URL")  # Optionnel : peut être null en dev
security = HTTPBearer()


# ─────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="Auth Service",
    description="Authentification centralisée via OpenLDAP + JWT",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
async def log_action(user_uid: str, action: str, details: dict = None, ip: str = None):
    """Envoie une entrée d'audit au log-service (fire and forget)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{LOG_SERVICE_URL}/logs", json={
                "user_uid": user_uid,
                "action": action,
                "resource_type": "auth",
                "resource_id": user_uid,
                "ip_address": ip,
                "details": details or {},
            })
    except Exception:
        pass  # Ne jamais bloquer l'auth si le log-service est indisponible


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else request.client.host


# ─────────────────────────────────────────────
# Dépendance : utilisateur courant
# ─────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")
    if await is_token_revoked(payload.get("jti")):
        raise HTTPException(status_code=401, detail="Token révoqué")
    return payload


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.post("/login", response_model=LoginResponse, tags=["Auth"])
async def login(req: LoginRequest, request: Request):
    """
    Authentifie un utilisateur via OpenLDAP.
    Retourne un JWT contenant uid, rôle et date d'expiration.
    """
    ip = get_client_ip(request)
    ldap = LDAPClient()

    try:
        user_info = ldap.authenticate(req.username, req.password)
    except LDAPInvalidCredentials:
        await log_action(req.username, "LOGIN_FAILED", {"reason": "invalid_credentials"}, ip)
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    except LDAPConnectionError as e:
        raise HTTPException(status_code=503, detail=f"Service LDAP indisponible : {e}")

    token, jti, expires_at = create_token(
        user_info["uid"], 
        user_info["role"], 
        user_info["display_name"]
    )
    await log_action(req.username, "LOGIN", {"role": user_info["role"]}, ip)

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        role=user_info["role"],
        uid=user_info["uid"],
        display_name=user_info["display_name"],
        email=user_info["email"],
        expires_at=expires_at.isoformat(),
    )


@app.post("/logout", tags=["Auth"])
async def logout(request: Request, current_user: dict = Depends(get_current_user)):
    """Révoque le token JWT de l'utilisateur courant."""
    ip = get_client_ip(request)
    await revoke_token(current_user["jti"], current_user["exp"])
    await log_action(current_user["uid"], "LOGOUT", {}, ip)
    return {"message": "Déconnexion réussie"}


@app.get("/verify", response_model=TokenVerifyResponse, tags=["Auth"])
async def verify(current_user: dict = Depends(get_current_user)):
    """
    Vérifie la validité d'un token JWT.
    Utilisé par les autres microservices pour valider les requêtes entrantes.
    """
    return TokenVerifyResponse(
        valid=True,
        uid=current_user["uid"],
        role=current_user["role"],
        expires_at=datetime.utcfromtimestamp(current_user["exp"]).isoformat(),
    )


@app.get("/health", tags=["Infra"])
async def health():
    """Healthcheck pour Kubernetes liveness/readiness probe."""
    ldap = LDAPClient()
    ldap_ok = ldap.ping()
    return {
        "status": "ok" if ldap_ok else "degraded",
        "ldap": "up" if ldap_ok else "down",
        "timestamp": datetime.utcnow().isoformat(),
    }
