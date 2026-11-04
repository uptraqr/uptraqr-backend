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
    _add_missing_columns()


def _add_missing_columns():
    """
    create_all() makes new tables but never adds new columns to tables that
    already exist. Add them here so existing databases keep working.
    """
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.begin() as cx:
        if "email_verified" not in cols:
            # Accounts that existed before email confirmation are treated as confirmed.
            cx.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE"))
        if "email_canonical" not in cols:
            cx.execute(text("ALTER TABLE users ADD COLUMN email_canonical VARCHAR"))
        cx.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email_canonical ON users (email_canonical)"))
        new_cols = {
            "stripe_customer_id": "VARCHAR",
            "stripe_subscription_id": "VARCHAR",
            "password_set": "BOOLEAN NOT NULL DEFAULT TRUE",
            "email_alerts": "BOOLEAN NOT NULL DEFAULT TRUE",
            "monthly_reports": "BOOLEAN NOT NULL DEFAULT TRUE",
            "status_slug": "VARCHAR",
            "timezone": "VARCHAR NOT NULL DEFAULT 'America/Vancouver'",
        }
        for col, kind in new_cols.items():
            if col not in cols:
                cx.execute(text(f"ALTER TABLE users ADD COLUMN {col} {kind}"))
        cx.execute(text("CREATE INDEX IF NOT EXISTS ix_users_stripe_customer ON users (stripe_customer_id)"))
        cx.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_status_slug ON users (status_slug)"))
        # Fill it in for accounts that don't have it yet
        from app.core.abuse import canonical_email
        for uid, email in cx.execute(text("SELECT id, email FROM users WHERE email_canonical IS NULL")).fetchall():
            cx.execute(text("UPDATE users SET email_canonical = :c WHERE id = :i"), {"c": canonical_email(email), "i": uid})
        # Fast lookups of a site's checks by time (works on both PostgreSQL and SQLite).
        cx.execute(text("CREATE INDEX IF NOT EXISTS ix_check_results_monitor_time ON check_results (monitor_id, checked_at)"))
        cx.execute(text("CREATE INDEX IF NOT EXISTS ix_incidents_monitor ON incidents (monitor_id)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
