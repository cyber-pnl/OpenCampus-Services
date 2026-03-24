# ─────────────────────────────────────────────
# Stage 1 : build des dépendances
# ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Dépendances système nécessaires pour python-ldap
RUN apt-get update && apt-get install -y --no-install-recommends \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────
# Stage 2 : image finale allégée
# ─────────────────────────────────────────────
FROM python:3.11-slim

# Runtime LDAP uniquement (pas les headers de dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libldap-2.5-0 \
    libsasl2-2 \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root pour la sécurité
RUN useradd -m -u 1001 appuser

WORKDIR /app

# Copier les dépendances compilées depuis le stage builder
COPY --from=builder /install /usr/local

# Copier le code source
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8001

# Healthcheck intégré Docker (en plus des probes Kubernetes)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--workers", "1", \
     "--log-level", "info"]
