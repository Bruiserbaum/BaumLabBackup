import logging
from datetime import datetime
from typing import Optional

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import DATABASE_URL

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def init_scheduler() -> BackgroundScheduler:
    global _scheduler
    jobstores = {
        "default": SQLAlchemyJobStore(url=DATABASE_URL),
    }
    _scheduler = BackgroundScheduler(jobstores=jobstores)
    _scheduler.start()
    logger.info("APScheduler started")
    return _scheduler


def get_scheduler() -> BackgroundScheduler:
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized. Call init_scheduler() first.")
    return _scheduler


def add_backup_job(job_id: int, job_name: str, cron_expr: str) -> None:
    from backup import execute_backup_job  # local import to avoid circular

    scheduler = get_scheduler()
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {cron_expr!r}")

    minute, hour, day, month, day_of_week = parts
    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )
    scheduler.add_job(
        execute_backup_job,
        trigger=trigger,
        id=f"backup_{job_id}",
        name=job_name,
        args=[job_id],
        replace_existing=True,
    )
    logger.info("Registered backup job %d (%s) with cron: %s", job_id, job_name, cron_expr)


def remove_backup_job(job_id: int) -> None:
    scheduler = get_scheduler()
    job_apid = f"backup_{job_id}"
    try:
        scheduler.remove_job(job_apid)
        logger.info("Removed scheduler job %s", job_apid)
    except Exception:
        pass  # silently handle job not found


def get_next_run_time(job_id: int) -> Optional[str]:
    scheduler = get_scheduler()
    job = scheduler.get_job(f"backup_{job_id}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def trigger_now(job_id: int) -> None:
    from backup import execute_backup_job  # local import to avoid circular

    scheduler = get_scheduler()
    ts = int(datetime.utcnow().timestamp())
    scheduler.add_job(
        execute_backup_job,
        id=f"manual_{job_id}_{ts}",
        name=f"manual_run_{job_id}",
        args=[job_id],
        replace_existing=True,
    )
    logger.info("Triggered manual backup for job %d", job_id)
