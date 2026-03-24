"""
test_auth.py — Tests unitaires auth-service
Lancer : pytest test_auth.py -v
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
import jwt
from datetime import datetime, timedelta

# On mocke les dépendances externes avant l'import de main
import sys
# Mock database
sys.modules["database"] = MagicMock(
    init_db=AsyncMock(),
    is_token_revoked=AsyncMock(return_value=False),
    revoke_token=AsyncMock(),
    check_db=AsyncMock(return_value=True),
)

# Mock ldap_client
sys.modules["ldap_client"] = MagicMock()
sys.modules["jwt_handler"] = MagicMock()

from main import app, create_token, decode_token, JWT_SECRET, JWT_ALGO

client = TestClient(app)


# ── Helpers ─────────────────────────────────────────────────────────────────

def make_token(uid="testuser", role="etudiant", expired=False):
    exp = datetime.utcnow() + timedelta(hours=-1 if expired else 8)
    payload = {
        "jti": "test-jti-123",
        "uid": uid,
        "role": role,
        "display_name": "Test User",
        "iat": datetime.utcnow(),
        "exp": exp,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ── Tests JWT ────────────────────────────────────────────────────────────────

def test_create_and_decode_token():
    token = create_token("jean", "etudiant", "Jean Dupont")
    payload = decode_token(token)
    assert payload["uid"] == "jean"
    assert payload["role"] == "etudiant"
    assert payload["display_name"] == "Jean Dupont"
    assert "jti" in payload


def test_decode_expired_token():
    from fastapi import HTTPException
    token = make_token(expired=True)
    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401
    assert "expiré" in exc.value.detail


def test_decode_invalid_token():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        decode_token("not.a.valid.token")
    assert exc.value.status_code == 401


# ── Tests endpoints ──────────────────────────────────────────────────────────

def test_health_ok():
    import database
    database.check_db = AsyncMock(return_value=True)
    with patch("main.ldap_connect_admin") as mock_ldap:
        mock_ldap.return_value = MagicMock()
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_verify_valid_token():
    import database
    database.is_token_revoked = AsyncMock(return_value=False)
    token = make_token()
    response = client.get("/verify", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["uid"] == "testuser"


def test_verify_revoked_token():
    import database
    database.is_token_revoked = AsyncMock(return_value=True)
    token = make_token()
    response = client.get("/verify", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_endpoint():
    import database
    database.is_token_revoked = AsyncMock(return_value=False)
    token = make_token(uid="agent1", role="personnel")
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["uid"] == "agent1"
    assert data["role"] == "personnel"


def test_login_invalid_credentials():
    with patch("main.ldap_authenticate_user") as mock_auth:
        from fastapi import HTTPException
        mock_auth.side_effect = HTTPException(status_code=401, detail="Identifiants invalides")
        response = client.post("/login", json={"username": "bad", "password": "wrong"})
    assert response.status_code == 401


def test_login_success():
    with patch("main.ldap_authenticate_user") as mock_auth, \
         patch("main.get_user_role") as mock_role, \
         patch("main.log_action", new=AsyncMock()):
        mock_auth.return_value = {
            "uid": "etudiant1",
            "display_name": "Jean Dupont",
            "mail": "jean@univ.fr"
        }
        mock_role.return_value = "etudiant"
        response = client.post("/login", json={"username": "etudiant1", "password": "etudiant123"})

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["role"] == "etudiant"
    assert data["uid"] == "etudiant1"