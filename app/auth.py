"""Authentifizierung & Benutzerrollen — eingebaut, ohne externen Dienst.

- Passwörter: PBKDF2-HMAC-SHA256 mit pro-Nutzer-Salt (nur Standardbibliothek).
- Sitzungen: serverseitige Tokens in der DB (widerrufbar), als HttpOnly-Cookie.
- Rollen: admin, vertrieb, fertigung, viewer — Rechte siehe `authorize()`.

Bewusst self-contained (passt zur Offline-Desktop-Variante). Ein Wechsel auf
einen externen Auth-Dienst wäre erst bei Cloud-SaaS sinnvoll.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import database

ROLES = ["admin", "vertrieb", "fertigung", "viewer"]
ROLE_LABELS = {
    "admin": "Administrator",
    "vertrieb": "Vertrieb",
    "fertigung": "Fertigung",
    "viewer": "Nur Lesen",
}

SESSION_TTL_DAYS = 7
_PBKDF2_ITERATIONS = 200_000


# ---------------------------------------------------------------------------
# Passwort-Hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(dk.hex(), digest)


# ---------------------------------------------------------------------------
# Benutzer
# ---------------------------------------------------------------------------


def count_users() -> int:
    return len(database.fetch_all("users"))


def get_user_by_email(email: str) -> Optional[dict]:
    rows = database.fetch_all("users", "email = ?", (email.strip().lower(),))
    return rows[0] if rows else None


def create_user(email: str, name: str, password: str, role: str = "viewer") -> dict:
    if role not in ROLES:
        raise ValueError("Ungültige Rolle")
    if get_user_by_email(email):
        raise ValueError("E-Mail bereits vergeben")
    uid = database.insert(
        "users",
        email=email.strip().lower(),
        name=name.strip(),
        password_hash=hash_password(password),
        role=role,
        active=1,
    )
    return _public(database.fetch_one("users", uid))


def update_user(user_id: int, *, name=None, role=None, active=None, password=None) -> dict:
    fields: dict = {}
    if name is not None:
        fields["name"] = name.strip()
    if role is not None:
        if role not in ROLES:
            raise ValueError("Ungültige Rolle")
        fields["role"] = role
    if active is not None:
        fields["active"] = 1 if active else 0
    if password:
        fields["password_hash"] = hash_password(password)
    if fields:
        database.update("users", user_id, **fields)
    return _public(database.fetch_one("users", user_id))


def list_users() -> list[dict]:
    return [_public(u) for u in database.fetch_all("users", order="email")]


def _public(user: Optional[dict]) -> Optional[dict]:
    if not user:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


# ---------------------------------------------------------------------------
# Sitzungen
# ---------------------------------------------------------------------------


def login(email: str, password: str) -> Optional[str]:
    """Prüft Zugangsdaten und gibt bei Erfolg ein Sitzungstoken zurück."""
    user = get_user_by_email(email)
    if not user or not user["active"] or not verify_password(password, user["password_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    database.insert(
        "sessions",
        token=token,
        user_id=user["id"],
        expires_at=(now + timedelta(days=SESSION_TTL_DAYS)).isoformat(),
    )
    return token


def user_for_token(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    rows = database.fetch_all("sessions", "token = ?", (token,), order="created_at DESC")
    if not rows:
        return None
    session = rows[0]
    try:
        expires = datetime.fromisoformat(session["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if expires < datetime.now(timezone.utc):
        logout(token)
        return None
    user = database.fetch_one("users", session["user_id"])
    if not user or not user["active"]:
        return None
    return _public(user)


def logout(token: Optional[str]) -> None:
    if token:
        with database.get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# ---------------------------------------------------------------------------
# Rechte (RBAC)
# ---------------------------------------------------------------------------

_ADMIN_WRITE_PREFIXES = ("/api/settings", "/api/material-prices")


def authorize(role: str, method: str, path: str) -> bool:
    """Entscheidet, ob eine Rolle eine Anfrage ausführen darf.

    Lesen (GET) darf jede angemeldete Rolle. Schreibrechte:
    - admin:     alles
    - vertrieb:  alles außer Benutzer-/Einstellungsverwaltung
    - fertigung: Projekte/Produktion/Zeit/Material/Dokumente, aber keine
                 Angebots-/Vertriebsaktionen und keine Verwaltung
    - viewer:    nur Lesen
    Benutzerverwaltung (/api/users) ist komplett admin-only (auch Lesen).
    """
    if role == "admin":
        return True
    if path.startswith("/api/users"):
        return False  # nur Admin
    is_write = method.upper() not in ("GET", "HEAD", "OPTIONS")
    if not is_write:
        return True
    if role == "viewer":
        return False
    if path.startswith(_ADMIN_WRITE_PREFIXES):
        return False  # Stammdaten/Preise nur Admin
    if role == "vertrieb":
        return True
    if role == "fertigung":
        sales_only = ("/api/inquiries", "/api/followups", "/api/offers", "/api/email")
        return not path.startswith(sales_only)
    return False
