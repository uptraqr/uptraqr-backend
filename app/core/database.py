import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base


def _database_url() -> str:
    """
    Use the PostgreSQL database Railway provides (DATABASE_URL) when it exists,
    so accounts and monitors survive every deploy. Without it (e.g. on your own
    computer) fall back to a local SQLite file.
    """
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return "sqlite:///./uptraqr.db"
    # Railway/Heroku style "postgres://" -> SQLAlchemy + psycopg 3 driver
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,   # quietly reconnect if the database restarted
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
