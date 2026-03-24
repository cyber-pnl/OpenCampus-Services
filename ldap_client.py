import ldap
import ldap.filter
import os
from dotenv import load_dotenv

load_dotenv()

import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Config LDAP (injectée via variables d'env Kubernetes)
# ─────────────────────────────────────────────
LDAP_HOST    = os.getenv("LDAP_HOST", "openldap-service")
LDAP_PORT    = int(os.getenv("LDAP_PORT", "389"))
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "dc=univ,dc=fr")
LDAP_BIND_DN = os.getenv("LDAP_BIND_DN", "cn=admin,dc=univ,dc=fr")
LDAP_BIND_PW = os.getenv("LDAP_BIND_PASSWORD")  # Obligatoire : doit être défini dans .env

# Mapping groupe LDAP → rôle applicatif
GROUP_ROLE_MAP = {
    "admins":     "admin",
    "personnels": "personnel",
    "etudiants":  "etudiant",
}


class LDAPConnectionError(Exception):
    pass


class LDAPInvalidCredentials(Exception):
    pass


class LDAPClient:
    def _connect(self) -> ldap.ldapobject.LDAPObject:
        """Ouvre une connexion LDAP et retourne l'objet de connexion."""
        try:
            uri = f"ldap://{LDAP_HOST}:{LDAP_PORT}"
            conn = ldap.initialize(uri)
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            conn.set_option(ldap.OPT_TIMEOUT, 5)
            conn.protocol_version = ldap.VERSION3
            return conn
        except Exception as e:
            raise LDAPConnectionError(f"Impossible de se connecter à {LDAP_HOST}:{LDAP_PORT} — {e}")

    def authenticate(self, username: str, password: str) -> dict:
        """
        Authentifie un utilisateur et retourne ses informations.

        Étapes :
        1. Bind admin pour rechercher le DN de l'utilisateur
        2. Bind avec les credentials de l'utilisateur pour vérifier le mot de passe
        3. Recherche des groupes pour déterminer le rôle
        """
        if not username or not password:
            raise LDAPInvalidCredentials("Identifiants manquants")

        conn = self._connect()

        try:
            # 1. Bind admin
            conn.simple_bind_s(LDAP_BIND_DN, LDAP_BIND_PW)

            # 2. Rechercher l'entrée utilisateur
            safe_username = ldap.filter.escape_filter_chars(username)
            results = conn.search_s(
                f"ou=users,{LDAP_BASE_DN}",
                ldap.SCOPE_SUBTREE,
                f"(uid={safe_username})",
                ["uid", "cn", "mail", "sn"],
            )

            if not results:
                raise LDAPInvalidCredentials("Utilisateur introuvable")

            user_dn, user_attrs = results[0]

            # 3. Vérifier le mot de passe en re-bindant avec les creds de l'user
            try:
                conn.simple_bind_s(user_dn, password)
            except ldap.INVALID_CREDENTIALS:
                raise LDAPInvalidCredentials("Mot de passe incorrect")

            # 4. Déterminer le rôle via les groupes
            role = self._get_role(conn, username)

            # 5. Extraire les attributs utilisateur
            def decode(attr):
                val = user_attrs.get(attr, [b""])[0]
                return val.decode("utf-8") if isinstance(val, bytes) else str(val)

            return {
                "uid":          username,
                "display_name": decode("cn"),
                "email":        decode("mail"),
                "role":         role,
            }

        except LDAPInvalidCredentials:
            raise
        except ldap.SERVER_DOWN as e:
            raise LDAPConnectionError(f"Serveur LDAP injoignable : {e}")
        except Exception as e:
            logger.error(f"Erreur LDAP inattendue : {e}")
            raise LDAPConnectionError(str(e))
        finally:
            try:
                conn.unbind_s()
            except Exception:
                pass

    def _get_role(self, conn: ldap.ldapobject.LDAPObject, uid: str) -> str:
        """
        Parcourt les groupes LDAP dans l'ordre de priorité (admin > personnel > etudiant)
        et retourne le rôle correspondant au premier groupe trouvé.
        """
        safe_uid = ldap.filter.escape_filter_chars(uid)
        user_dn = f"uid={safe_uid},ou=users,{LDAP_BASE_DN}"

        for group_cn, role in GROUP_ROLE_MAP.items():
            try:
                results = conn.search_s(
                    f"cn={group_cn},ou=groups,{LDAP_BASE_DN}",
                    ldap.SCOPE_BASE,
                    f"(member={user_dn})",
                    ["cn"],
                )
                if results:
                    logger.debug(f"Utilisateur {uid} → rôle '{role}' (groupe {group_cn})")
                    return role
            except ldap.NO_SUCH_OBJECT:
                continue
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification du groupe {group_cn} : {e}")
                continue

        logger.warning(f"Aucun groupe trouvé pour {uid}, rôle par défaut : etudiant")
        return "etudiant"

    def ping(self) -> bool:
        """Vérifie que le serveur LDAP est joignable (utilisé par le healthcheck)."""
        try:
            conn = self._connect()
            conn.simple_bind_s(LDAP_BIND_DN, LDAP_BIND_PW)
            conn.unbind_s()
            return True
        except Exception:
            return False
