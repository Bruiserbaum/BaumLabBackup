import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import ADMIN_PASSWORD, BACKUP_TMP_DIR
from database import BackupJob, User, get_db, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    os.makedirs(BACKUP_TMP_DIR, exist_ok=True)
    os.makedirs("/data", exist_ok=True)

    init_db()

    # Create admin user if no users exist
    db = next(get_db())
    try:
        if db.query(User).count() == 0:
            from auth import hash_password
            admin = User(
                username="admin",
                password_hash=hash_password(ADMIN_PASSWORD),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
            logger.info("Created default admin user")
    finally:
        db.close()

    # Init scheduler
    from scheduler import add_backup_job, init_scheduler
    init_scheduler()

    # Re-register all enabled jobs
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

    yield

    # Shutdown
    from scheduler import get_scheduler
    try:
        scheduler = get_scheduler()
        scheduler.shutdown(wait=False)
    except Exception:
        pass


app = FastAPI(title="BaumLabBackup", version="1.0.0", lifespan=lifespan)

from routers import auth_router, destinations_router, jobs_router, status_router

app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(jobs_router.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(destinations_router.router, prefix="/api/destinations", tags=["destinations"])
app.include_router(status_router.router, prefix="/api/status", tags=["status"])

app.mount("/", StaticFiles(directory="static", html=True), name="static")
