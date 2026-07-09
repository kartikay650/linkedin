from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

from app.config import settings

# On serverless (Vercel) each function invocation is short-lived and there can be
# many concurrent ones, so we must NOT hold a connection pool — use NullPool and
# point DATABASE_URL at Supabase's transaction pooler (pgBouncer, port 6543).
# Locally we keep a normal pooled engine with pre-ping.
if settings.serverless:
    engine = create_engine(settings.database_url, poolclass=NullPool)
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
