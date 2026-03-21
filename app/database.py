from datetime import datetime
from typing import Generator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    totp_secret = Column(String, nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    oidc_sub = Column(String, unique=True, nullable=True, index=True)


class Destination(Base):
    __tablename__ = "destinations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # b2 / smb / sftp / local
    config_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BackupJob(Base):
    __tablename__ = "backup_jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    containers = Column(Text, nullable=False, default="[]")   # JSON list of container names
    volumes = Column(Text, nullable=False, default="[]")      # JSON list of {source, name}
    db_type = Column(String, nullable=True)                   # mysql / postgres / None
    db_container = Column(String, nullable=True)
    db_name = Column(String, nullable=True)
    db_user = Column(String, nullable=True)
    db_password_encrypted = Column(Text, nullable=True)
    destination_id = Column(Integer, ForeignKey("destinations.id"), nullable=False)
    schedule_cron = Column(String, nullable=False)
    pre_stop = Column(Boolean, default=False, nullable=False)
    retention_days = Column(Integer, default=30, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String, nullable=True)


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("backup_jobs.id", ondelete="SET NULL"), nullable=True)
    job_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="running")  # running / success / failed
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    destination_path = Column(String, nullable=True)
    log_lines = Column(Text, nullable=False, default="[]")   # JSON list of strings
    error = Column(Text, nullable=True)


class Stack(Base):
    __tablename__ = "stacks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    repo_url = Column(String, nullable=False)
    repo_branch = Column(String, nullable=False, default="main")
    env_path = Column(String, nullable=False, default="")   # absolute host path to .env
    compose_project = Column(String, nullable=False)         # docker compose project name
    volumes = Column(Text, nullable=False, default="[]")     # JSON list of volume names
    destination_id = Column(Integer, ForeignKey("destinations.id"), nullable=False)
    schedule_cron = Column(String, nullable=True)            # optional; None = manual only
    retention_days = Column(Integer, default=30, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_backup_at = Column(DateTime, nullable=True)
    last_backup_status = Column(String, nullable=True)       # success / failed


class StackRun(Base):
    __tablename__ = "stack_runs"

    id = Column(Integer, primary_key=True, index=True)
    stack_id = Column(Integer, ForeignKey("stacks.id", ondelete="SET NULL"), nullable=True)
    stack_name = Column(String, nullable=False)
    run_type = Column(String, nullable=False)                # backup / restore
    status = Column(String, nullable=False, default="running")  # running / success / failed
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    backup_path = Column(String, nullable=True)              # remote path (backup) or filename (restore)
    restore_target = Column(String, nullable=True)           # clone target dir (restore only)
    log_lines = Column(Text, nullable=False, default="[]")   # JSON list of strings
    error = Column(Text, nullable=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def migrate_db() -> None:
    """Add new columns to existing tables (SQLite ALTER TABLE, idempotent)."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE users ADD COLUMN oidc_sub TEXT UNIQUE",
        "CREATE INDEX IF NOT EXISTS ix_users_oidc_sub ON users (oidc_sub)",
        # Stack tables added later — CREATE TABLE IF NOT EXISTS handles fresh installs;
        # existing installs without these tables will create them via init_db on restart.
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # Column / index already exists
