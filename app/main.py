import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import ADMIN_PASSWORD, ADMIN_RESET, BACKUP_TMP_DIR
from database import BackupJob, Stack, User, get_db, init_db, migrate_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    os.makedirs(BACKUP_TMP_DIR, exist_ok=True)
    os.makedirs("/data", exist_ok=True)

    init_db()
    migrate_db()

    # Create or reset admin user
    db = next(get_db())
    try:
        from auth import hash_password
        existing = db.query(User).filter(User.username == "admin").first()
        if existing and ADMIN_RESET:
            existing.password_hash = hash_password(ADMIN_PASSWORD)
            db.commit()
            logger.info("Admin user password reset (ADMIN_RESET=true). Password length: %d", len(ADMIN_PASSWORD))
        elif not existing:
            admin = User(
                username="admin",
                password_hash=hash_password(ADMIN_PASSWORD),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
            logger.info("Created admin user. Password length: %d", len(ADMIN_PASSWORD))
        else:
            logger.info("Admin user exists. Password length in env: %d (set ADMIN_RESET=true to force reset)", len(ADMIN_PASSWORD))
    finally:
        db.close()

    # Init scheduler
    from scheduler import add_backup_job, add_stack_job, init_scheduler
    init_scheduler()

    # Re-register all enabled backup jobs
    db = next(get_db())
    try:
        enabled_jobs = db.query(BackupJob).filter(BackupJob.enabled == True).all()
        for job in enabled_jobs:
            try:
                add_backup_job(job.id, job.name, job.schedule_cron)
            except Exception as exc:
                logger.error("Failed to register job %d: %s", job.id, exc)
        logger.info("Re-registered %d backup job(s)", len(enabled_jobs))
    finally:
        db.close()

    # Re-register all enabled stack backup jobs (scheduled only)
    db = next(get_db())
    try:
        enabled_stacks = (
            db.query(Stack)
            .filter(Stack.enabled == True, Stack.schedule_cron.isnot(None))
            .all()
        )
        for s in enabled_stacks:
            try:
                add_stack_job(s.id, s.name, s.schedule_cron)
            except Exception as exc:
                logger.error("Failed to register stack job %d: %s", s.id, exc)
        logger.info("Re-registered %d stack job(s)", len(enabled_stacks))
    finally:
        db.close()

    yield

    # Shutdown
    from scheduler import get_scheduler
    try:
        scheduler = get_scheduler()
        scheduler.shutdown(wait=False)
    except Exception:
        pass


app = FastAPI(title="BaumLabBackup", version="1.0.0", lifespan=lifespan)

from routers import auth_router, destinations_router, jobs_router, stacks_router, status_router

app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(jobs_router.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(destinations_router.router, prefix="/api/destinations", tags=["destinations"])
app.include_router(stacks_router.router, prefix="/api/stacks", tags=["stacks"])
app.include_router(status_router.router, prefix="/api/status", tags=["status"])

app.mount("/", StaticFiles(directory="static", html=True), name="static")
