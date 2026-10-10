"""SQLAlchemy database configuration. SQLite is the zero-setup local default."""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured
    host = os.getenv("SFA_DB_HOST")
    if host:
        return URL.create(
            "postgresql+psycopg",
            username=os.getenv("SFA_DB_USER", "sfa"),
            password=os.getenv("SFA_DB_PASSWORD"),
            host=host,
            port=int(os.getenv("SFA_DB_PORT", "5432")),
            database=os.getenv("SFA_DB_NAME", "smart_farm"),
        ).render_as_string(hide_password=False)
    return "sqlite:///./backend/data/smart_farm.db"


def make_engine(url: str | None = None) -> Engine:
    value = url or database_url()
    kwargs = {"pool_pre_ping": True}
    if value.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if value.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
        if value.startswith("sqlite:///") and value != "sqlite:///:memory:":
            Path(value.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(value, **kwargs)
    if value.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_weather_coordinates(engine: Engine) -> None:
    """Forward-compatible, nullable schema upgrade for existing farm databases."""
    columns = {column["name"] for column in inspect(engine).get_columns("farms")}
    with engine.begin() as connection:
        if "latitude" not in columns:
            connection.execute(text("ALTER TABLE farms ADD COLUMN latitude NUMERIC(9, 6)"))
        if "longitude" not in columns:
            connection.execute(text("ALTER TABLE farms ADD COLUMN longitude NUMERIC(9, 6)"))
        if "irrigation_efficiency" not in columns:
            connection.execute(text("ALTER TABLE farms ADD COLUMN irrigation_efficiency NUMERIC(7, 6)"))
        if "effective_rain_fraction" not in columns:
            connection.execute(text("ALTER TABLE farms ADD COLUMN effective_rain_fraction NUMERIC(7, 6)"))
        connection.execute(text(
            "UPDATE farms SET latitude = 32.19, longitude = 35.62, "
            "irrigation_efficiency = COALESCE(irrigation_efficiency, 0.9), "
            "effective_rain_fraction = COALESCE(effective_rain_fraction, 0.8) "
            "WHERE data_origin = 'sample' AND location LIKE '%Jordan Valley%' "
            "AND (latitude IS NULL OR longitude IS NULL)"
        ))


def get_session(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
    finally:
        session.close()
