"""One SQLAlchemy engine for SQLite in dev and PostgreSQL on Spark."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import database_url


class Base(DeclarativeBase):
    pass


class ModelProbe(Base):
    __tablename__ = "model_probes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(200), index=True)
    first_token_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    probed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


_engine = None
_factory = None


def engine():
    global _engine, _factory
    if _engine is None:
        url = database_url()
        args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=args, pool_pre_ping=True)
        _factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session() -> Session:
    engine()
    return _factory()


def init_db() -> None:
    Base.metadata.create_all(engine())


def reset_engine() -> None:
    """Tests swap DATABASE_URL and need a fresh engine."""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def ranked_models(db: Session) -> list[str]:
    """Fastest successful probe first. The latest probe for a name wins."""
    rows = db.scalars(select(ModelProbe).order_by(ModelProbe.probed_at.desc())).all()
    latest: dict[str, ModelProbe] = {}
    for row in rows:
        latest.setdefault(row.model_name, row)
    ok = [row for row in latest.values() if row.ok and row.first_token_ms is not None]
    ok.sort(key=lambda row: row.first_token_ms)
    return [row.model_name for row in ok]


def record_probe(db: Session, model_name: str, first_token_ms: float | None, ok: bool, error: str = "") -> None:
    db.add(ModelProbe(
        model_name=model_name,
        first_token_ms=first_token_ms,
        ok=ok,
        error=error[:500],
        probed_at=datetime.now(timezone.utc),
    ))
    db.commit()
