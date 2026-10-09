"""Comptes et sessions.

  - Rôles : « admin » (tout, dont piloter la caméra / le moteur et gérer les comptes) et « agent »
    (consultation seule : tableau de bord, vidéo, alertes, photos).
  - Mots de passe : scrypt (bibliothèque standard), sel aléatoire. Jamais stockés en clair.
  - Sessions : jeton aléatoire dans un cookie HttpOnly ; seule son empreinte SHA-256 est en base.
  - Le cookie accompagne aussi les WebSocket du dashboard (même origine), voir `websocket_user`.
  - Trop de tentatives de connexion ratées : temporairement refusées (429).
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, Field

from .config import config
from .console import green
from .db import database

COOKIE = "sentinel_session"
ROLES = ("admin", "agent")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8
MAX_FAILURES, FAILURE_WINDOW_S = 5, 300  # 5 échecs en 5 min pour un même (adresse, identifiant) : refus temporaire

log = logging.getLogger("sentinel-x")


# ---- mots de passe ----
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("pas-un-vrai-mot-de-passe")  # identifiant inconnu : on calcule quand même, même durée


# ---- sessions ----
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def open_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = int((time.time() + config.auth.session_hours * 3600) * 1000)
    database.create_session(_token_hash(token), user_id, expires_at)
    return token


def user_from_token(token: str | None) -> dict | None:
    return database.user_for_session(_token_hash(token)) if token else None


def current_user(request: Request) -> dict:
    """Dépendance FastAPI : l'utilisateur connecté, sinon 401."""
    user = user_from_token(request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Non authentifié")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    """Dépendance FastAPI : un admin, sinon 403 (un agent est en consultation seule)."""
    if user["role"] != "admin":
        raise HTTPException(403, "Réservé aux administrateurs")
    return user


async def websocket_user(ws: WebSocket) -> dict | None:
    """L'utilisateur d'une WebSocket, d'après le cookie de session envoyé à la poignée de main."""
    return await asyncio.to_thread(user_from_token, ws.cookies.get(COOKIE))


def device_token_ok(token: str | None) -> bool:
    """Jeton des appareils (Raspberry) pour /ws/camera ; désactivé si DEVICE_TOKEN est vide."""
    expected = config.auth.device_token
    return bool(expected) and bool(token) and hmac.compare_digest(token.encode(), expected.encode())


# ---- limitation des tentatives ----
_failures: dict[str, deque] = defaultdict(deque)


def _check_rate(key: str) -> None:
    now, attempts = time.time(), _failures[key]
    while attempts and now - attempts[0] > FAILURE_WINDOW_S:
        attempts.popleft()
    if len(attempts) >= MAX_FAILURES:
        raise HTTPException(429, "Trop de tentatives, réessayez dans quelques minutes")


# ---- premier lancement ----
def bootstrap_admin() -> None:
    """Crée les comptes du .env absents de la base : admin (ADMIN_*) s'il n'existe aucun utilisateur, agent (AGENT_*).

    Un compte déjà présent n'est jamais modifié (changer le mot de passe dans le .env ne change pas celui de la base :
    `python -m app.cli passwd <identifiant>`).
    """
    cfg = config.auth
    if not database.count_users():
        password = cfg.admin_password or secrets.token_urlsafe(9)
        database.create_user(cfg.admin_username, hash_password(password), "admin")
        database.audit(None, "bootstrap", f"compte admin « {cfg.admin_username} » créé")
        if cfg.admin_password:
            log.info(green(f"compte admin « {cfg.admin_username} » créé (mot de passe : variable ADMIN_PASSWORD)"))
        else:
            log.warning(green(f"COMPTE ADMIN CRÉÉ — identifiant : {cfg.admin_username} · mot de passe : {password}  (affiché une seule fois, à noter)"))
    if cfg.agent_password and database.get_user_by_name(cfg.agent_username) is None:
        if len(cfg.agent_password) < MIN_PASSWORD_LENGTH:
            log.warning(f"AGENT_PASSWORD trop court ({MIN_PASSWORD_LENGTH} caractères minimum) : compte agent non créé")
            return
        database.create_user(cfg.agent_username, hash_password(cfg.agent_password), "agent")
        database.audit(None, "bootstrap", f"compte agent « {cfg.agent_username} » créé")
        log.info(green(f"compte agent « {cfg.agent_username} » créé (mot de passe : variable AGENT_PASSWORD)"))


# ---- routes ----
router = APIRouter(prefix="/api")


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


class NewUserBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)
    role: str = Field(max_length=10)


class PasswordBody(BaseModel):
    password: str = Field(max_length=200)


def _require_long_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Mot de passe : {MIN_PASSWORD_LENGTH} caractères minimum")


def _public(user: dict) -> dict:
    return {"username": user["username"], "role": user["role"]}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    key = f"{request.client.host if request.client else '?'}|{body.username.lower()}"
    _check_rate(key)
    user = database.get_user_by_name(body.username)
    valid = verify_password(body.password, user["passwordHash"] if user else _DUMMY_HASH)
    if not (user and valid):
        _failures[key].append(time.time())
        database.audit(body.username[:32], "login_failed", f"depuis {request.client.host if request.client else '?'}")
        raise HTTPException(401, "Identifiant ou mot de passe incorrect")
    _failures.pop(key, None)
    database.purge_sessions()
    token = open_session(user["id"])
    response.set_cookie(
        COOKIE, token, max_age=int(config.auth.session_hours * 3600), httponly=True, samesite="lax",
        secure=config.auth.cookie_secure, path="/",
    )
    database.audit(user["username"], "login", f"depuis {request.client.host if request.client else '?'}")
    return _public(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: dict = Depends(current_user)):
    database.delete_session(_token_hash(request.cookies[COOKIE]))
    response.delete_cookie(COOKIE, path="/")
    database.audit(user["username"], "logout", f"depuis {request.client.host if request.client else '?'}")
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return _public(user)


@router.get("/users")
def list_users(_admin: dict = Depends(require_admin)):
    return database.list_users()


@router.post("/users", status_code=201)
def create_user(body: NewUserBody, admin: dict = Depends(require_admin)):
    if not USERNAME_RE.match(body.username):
        raise HTTPException(400, "Identifiant : 3 à 32 caractères (lettres, chiffres, _ . -)")
    if body.role not in ROLES:
        raise HTTPException(400, "Rôle attendu : admin ou agent")
    _require_long_password(body.password)
    user = database.create_user(body.username, hash_password(body.password), body.role)
    if user is None:
        raise HTTPException(409, "Cet identifiant existe déjà")
    database.audit(admin["username"], "user_create", f"{user['username']} ({user['role']})")
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    target = next((u for u in database.list_users() if u["id"] == user_id), None)
    if target is None:
        raise HTTPException(404, "Utilisateur introuvable")
    if target["id"] == admin["id"]:
        raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte")
    if target["role"] == "admin" and database.count_admins() <= 1:
        raise HTTPException(400, "Impossible de supprimer le dernier administrateur")
    database.delete_user(user_id)
    database.audit(admin["username"], "user_delete", target["username"])
    return {"ok": True}


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordBody, admin: dict = Depends(require_admin)):
    _require_long_password(body.password)
    if not database.set_password(user_id, hash_password(body.password)):
        raise HTTPException(404, "Utilisateur introuvable")
    database.audit(admin["username"], "password_reset", f"utilisateur #{user_id}")
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 50, _admin: dict = Depends(require_admin)):
    return database.recent_audit(min(max(limit, 1), 500))
