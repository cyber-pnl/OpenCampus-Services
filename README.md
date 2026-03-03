# Plateforme de Dématérialisation Universitaire

> Mini service numérique universitaire — Authentification LDAP centralisée, dépôt de documents, workflow de validation, journalisation des actions. Déployé en microservices sur Kubernetes.

---

## Sommaire

- [Présentation](#présentation)
- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Installation rapide](#installation-rapide)
- [Services](#services)
- [Authentification et rôles](#authentification-et-rôles)
- [Utilisation](#utilisation)
- [Base de données](#base-de-données)
- [Scripts d'exploitation](#scripts-dexploitation)
- [Structure du projet](#structure-du-projet)
- [Développement local](#développement-local)
- [FAQ / Dépannage](#faq--dépannage)

---

## Présentation

Cette plateforme permet à une université de dématérialiser ses demandes administratives. Elle repose sur une architecture microservices déployée sous Kubernetes, avec une authentification centralisée via OpenLDAP.

**Fonctionnalités principales :**

- Connexion unifiée via l'annuaire LDAP de l'établissement
- Dépôt de documents par les étudiants et personnels
- Workflow de validation par le supérieur hiérarchique (N+1)
- Journal d'audit horodaté de toutes les actions
- Contrôle d'accès basé sur les rôles (étudiant / personnel / admin)

**Stack technique :**

| Composant | Technologie |
|---|---|
| Orchestration | Kubernetes (Minikube ou k8s) |
| Reverse proxy | Nginx Ingress Controller |
| Backend | Python 3.11 + FastAPI |
| Base de données | PostgreSQL 15 |
| Annuaire | OpenLDAP |
| Authentification | JWT (python-jose) |
| Frontend | React 18 + Nginx |
| Stockage fichiers | PersistentVolumeClaim (Kubernetes) |

---

## Architecture
```
                    ┌─────────────────────────────────────┐
                    │      INGRESS NGINX  demat.local      │
                    └──────┬──────────┬──────────┬─────────┘
                           │          │          │
                        /auth    /api/docs  /api/workflow
                           │          │          │
                    ┌──────▼──┐ ┌─────▼────┐ ┌──▼──────────┐
                    │  AUTH   │ │ DOCUMENT │ │  WORKFLOW   │
                    │ SERVICE │ │ SERVICE  │ │  SERVICE    │
                    │  :8001  │ │  :8002   │ │   :8003     │
                    └──────┬──┘ └─────┬────┘ └──┬──────────┘
                           │          │          │
                       auth_db    docs_db +   workflow_db
                                   PVC files
                           │
                    ┌──────▼──────┐     ┌──────────────────┐
                    │  OPENLDAP   │     │   LOG SERVICE    │
                    │    :389     │     │     :8004        │
                    └─────────────┘     └──────┬───────────┘
                                               │
                                           logs_db
                    ┌─────────────┐
                    │  FRONTEND   │  ← Servi par Nginx :3000
                    │   React     │
                    └─────────────┘
```

**Flux d'une demande :**
```
Étudiant  →  login LDAP  →  JWT token
          →  POST /api/docs/upload (+ JWT)
          →  Document stocké + Workflow créé
          →  Agent N+1 reçoit la notification
          →  Agent valide ou refuse avec commentaire
          →  Action loguée dans audit_logs
```

---

## Prérequis

- Ubuntu 20.04+ (ou tout OS avec Docker)
- 4 CPU / 8 Go RAM minimum
- `kubectl` installé
- `minikube` **ou** `k3s` installé
- `docker` installé et actif
```bash
kubectl version --client
docker --version
minikube version
```

---

## Installation rapide

### 1. Cloner le dépôt
```bash
git clone https://github.com/votre-org/demat-platform.git
cd demat-platform
```

### 2. Démarrer le cluster Kubernetes

**Option A — Minikube :**
```bash
minikube start --cpus=4 --memory=8192
minikube addons enable ingress
```

**Option B — k3s (serveur Ubuntu) :**
```bash
curl -sfL https://get.k3s.io | sh -
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
```

### 3. Déployer en une commande
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

### 4. Configurer l'accès local
```bash
# Minikube
echo "$(minikube ip) demat.local" | sudo tee -a /etc/hosts

# k3s
echo "127.0.0.1 demat.local" | sudo tee -a /etc/hosts
```

### 5. Accéder à la plateforme

Navigateur : **http://demat.local**

| Identifiant | Mot de passe | Rôle |
|---|---|---|
| etudiant1 | etudiant123 | Étudiant |
| agent1 | agent123 | Personnel (valideur) |
| admin1 | admin123 | Administrateur |

---

## Services

### auth-service — port 8001

| Endpoint | Méthode | Description |
|---|---|---|
| `/auth/login` | POST | Connexion LDAP → JWT |
| `/auth/verify` | GET | Vérifie un token |
| `/auth/logout` | POST | Révoque le token |
| `/auth/health` | GET | Healthcheck |
```bash
curl -X POST http://demat.local/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "etudiant1", "password": "etudiant123"}'
```
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1...",
  "role": "etudiant",
  "expires_in": 28800
}
```

---

## Authentification et rôles

| Groupe LDAP | Rôle | Permissions |
|---|---|---|
| `cn=etudiants` | etudiant | Dépôt et consultation de ses docs |
| `cn=personnels` | personnel | + Validation et refus |
| `cn=admins` | admin | Accès total + logs |

**Structure LDAP :**
```
dc=univ,dc=fr
├── ou=users
│   ├── uid=etudiant1
│   ├── uid=agent1
│   └── uid=admin1
└── ou=groups
    ├── cn=etudiants
    ├── cn=personnels
    └── cn=admins
```



## Utilisation



### Parcours agent (N+1)

1. Se connecter avec un compte `personnels`
2. Accéder à **"Demandes en attente"**
3. Ouvrir une demande, consulter le document
4. **Valider** ou **Refuser** avec un commentaire obligatoire

### Parcours administrateur

1. Se connecter avec un compte `admins`
2. Accès à toutes les demandes et tous les utilisateurs
3. Consultation et export du journal d'audit

---

## Base de données

| Base | Service | Contenu |
|---|---|---|
| `auth_db` | auth-service | Tokens révoqués |
| `documents_db` | document-service | Métadonnées des fichiers |
| `workflow_db` | workflow-service | Workflows et historique |



---

## Scripts d'exploitation




### Commandes kubectl utiles


## Développement local
```bash
cd services/auth-service
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

**Variables d'environnement (`.env`) :**
=
```

**Swagger UI par service :**
```
http://localhost:8001/docs   →  auth-service
http://localhost:8002/docs   →  document-service
http://localhost:8003/docs   →  workflow-service
http://localhost:8004/docs   →  log-service
```

**Rebuild image avec Minikube :**
```bash
docker build -t demat/auth-service:latest ./services/auth-service
minikube image load demat/auth-service:latest
kubectl rollout restart deploy/auth-service -n demat
```

---

## FAQ / Dépannage

**Pods en `Pending` après déploiement**
```bash
kubectl describe pod <nom-du-pod> -n demat
```

Cause fréquente : ressources insuffisantes — augmenter CPU/RAM de Minikube.

---


## Auteur

Projet réalisé dans le cadre d'une mission en service numérique universitaire.  
Stack : Python · FastAPI · PostgreSQL · OpenLDAP · Kubernetes · React