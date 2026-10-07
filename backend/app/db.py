"""Base de données : utilisateurs, sessions, historique des alertes, journal d'audit.

SQLAlchemy 2 : le même code tourne sur SQLite (défaut, un simple fichier) et sur PostgreSQL
(DATABASE_URL=postgresql+psycopg://utilisateur:motdepasse@hote:5432/base). Les tables sont créées au démarrage.
Les méthodes sont synchrones et retournent des dict simples ; depuis du code async, les appeler avec
`asyncio.to_thread(...)`.
"""
import time
from pathlib import Path

from sqlalchemy import BigInteger, Index, Integer, String, Text, create_engine, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _now_ms() -> int:
    return int(time.time() * 1000)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    # la connexion ignore la casse : l'unicité aussi (« Agent1 » et « agent1 » seraient deux comptes ambigus)
    __table_args__ = (Index("uq_users_username_lower", func.lower(text("username")), unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10))  # "admin" | "agent"
    created_at: Mapped[int] = mapped_column(BigInteger)


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 du jeton : le jeton lui-même n'est jamais stocké
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int] = mapped_column(BigInteger)


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # id attribué par le moteur d'alertes
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    level: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)  # URL de la photo d'intrusion


class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")


def _user(row: User) -> dict:  # noqa: D103 — voir `database` en bas du fichier pour l'instance partagée
    return {"id": row.id, "username": row.username, "role": row.role, "createdAt": row.created_at}


class Database:
    def __init__(self, url: str):
        self.url = url
        if url.startswith("sqlite"):
            # le thread de l'API et ses threads de travail partagent le fichier
            self.engine = create_engine(url, connect_args={"check_same_thread": False})
        else:
            self.engine = create_engine(url, pool_pre_ping=True)
        self._session = sessionmaker(self.engine, expire_on_commit=False)

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    def init(self) -> None:
        if self.dialect == "sqlite":  # le dossier du fichier doit exister
            path = self.engine.url.database
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)

    # ---- utilisateurs ----
    def count_users(self) -> int:
        with self._session() as s:
            return s.scalar(select(func.count()).select_from(User)) or 0

    def count_admins(self) -> int:
        with self._session() as s:
            return s.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0

    def get_user_by_name(self, username: str) -> dict | None:
        with self._session() as s:
            row = s.scalar(select(User).where(func.lower(User.username) == username.lower()))
            return {**_user(row), "passwordHash": row.password_hash} if row else None

    def list_users(self) -> list[dict]:
        with self._session() as s:
            return [_user(r) for r in s.scalars(select(User).order_by(User.id))]

    def create_user(self, username: str, password_hash: str, role: str) -> dict | None:
        """None si ce nom d'utilisateur existe déjà."""
        with self._session() as s:
            if s.scalar(select(User.id).where(func.lower(User.username) == username.lower())) is not None:
                return None
            row = User(username=username, password_hash=password_hash, role=role, created_at=_now_ms())
            s.add(row)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                return None
            return _user(row)

    def delete_user(self, user_id: int) -> bool:
        with self._session() as s:
            s.execute(delete(SessionRow).where(SessionRow.user_id == user_id))  # déconnecte l'utilisateur supprimé
            deleted = s.execute(delete(User).where(User.id == user_id)).rowcount
            s.commit()
            return bool(deleted)

    def set_password(self, user_id: int, password_hash: str) -> bool:
        with self._session() as s:
            row = s.get(User, user_id)
            if row is None:
                return False
            row.password_hash = password_hash
            s.execute(delete(SessionRow).where(SessionRow.user_id == user_id))  # ancien mot de passe : sessions fermées
            s.commit()
            return True

    # ---- sessions ----
    def create_session(self, token_hash: str, user_id: int, expires_at: int) -> None:
        with self._session() as s:
            s.add(SessionRow(token_hash=token_hash, user_id=user_id, created_at=_now_ms(), expires_at=expires_at))
            s.commit()

    def user_for_session(self, token_hash: str) -> dict | None:
        with self._session() as s:
            row = s.get(SessionRow, token_hash)
            if row is None or row.expires_at < _now_ms():
                return None
            user = s.get(User, row.user_id)
            return _user(user) if user else None

    def delete_session(self, token_hash: str) -> None:
        with self._session() as s:
            s.execute(delete(SessionRow).where(SessionRow.token_hash == token_hash))
            s.commit()

    def purge_sessions(self) -> None:
        with self._session() as s:
            s.execute(delete(SessionRow).where(SessionRow.expires_at < _now_ms()))
            s.commit()

    # ---- alertes ----
    def save_alerts(self, alerts: list[dict]) -> None:
        with self._session() as s:
            for a in alerts:
                s.merge(AlertRow(id=a["id"], ts=a["ts"], level=a["level"], key=a["key"], message=a["message"], snapshot=a.get("snapshot")))
            s.commit()

    def recent_alerts(self, limit: int) -> list[dict]:
        """Les plus récentes d'abord (même forme que les alertes du moteur : `snapshot` seulement s'il y a une photo)."""
        with self._session() as s:
            rows = s.scalars(select(AlertRow).order_by(AlertRow.id.desc()).limit(limit))
            return [
                {"id": r.id, "ts": r.ts, "level": r.level, "key": r.key, "message": r.message, **({"snapshot": r.snapshot} if r.snapshot else {})}
                for r in rows
            ]

    # ---- audit ----
    def audit(self, username: str | None, action: str, detail: str = "") -> None:
        with self._session() as s:
            s.add(AuditRow(ts=_now_ms(), username=username, action=action, detail=detail[:2000]))
            s.commit()

    def recent_audit(self, limit: int) -> list[dict]:
        with self._session() as s:
            rows = s.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit))
            return [{"id": r.id, "ts": r.ts, "username": r.username, "action": r.action, "detail": r.detail} for r in rows]


# Instance partagée par l'API (créée à l'import ; la connexion n'est ouverte qu'à la première requête).
from .config import config  # noqa: E402

database = Database(config.auth.database_url)
