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


# ── Stack scheduling ───────────────────────────────────────────────────────────

def add_stack_job(stack_id: int, stack_name: str, cron_expr: str) -> None:
    from backup_stack import execute_stack_backup

    scheduler = get_scheduler()
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {cron_expr!r}")

    minute, hour, day, month, day_of_week = parts
    trigger = CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week,
    )
    scheduler.add_job(
        execute_stack_backup,
        trigger=trigger,
        id=f"stack_{stack_id}",
        name=stack_name,
        args=[stack_id],
        replace_existing=True,
    )
    logger.info("Registered stack job %d (%s) cron: %s", stack_id, stack_name, cron_expr)


def remove_stack_job(stack_id: int) -> None:
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(f"stack_{stack_id}")
        logger.info("Removed stack scheduler job stack_%d", stack_id)
    except Exception:
        pass


def get_stack_next_run_time(stack_id: int) -> Optional[str]:
    scheduler = get_scheduler()
    job = scheduler.get_job(f"stack_{stack_id}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def trigger_stack_now(stack_id: int) -> None:
    from backup_stack import execute_stack_backup

    scheduler = get_scheduler()
    ts = int(datetime.utcnow().timestamp())
    scheduler.add_job(
        execute_stack_backup,
        id=f"stack_manual_{stack_id}_{ts}",
        name=f"stack_manual_{stack_id}",
        args=[stack_id],
        replace_existing=True,
    )
    logger.info("Triggered manual stack backup for stack %d", stack_id)


def trigger_stack_restore(
    stack_id: int,
    backup_filename: str,
    restore_target_dir: str,
    auto_start: bool,
) -> None:
    from restore import execute_stack_restore

    scheduler = get_scheduler()
    ts = int(datetime.utcnow().timestamp())
    scheduler.add_job(
        execute_stack_restore,
        id=f"restore_{stack_id}_{ts}",
        name=f"restore_{stack_id}",
        args=[stack_id, backup_filename, restore_target_dir, auto_start],
        replace_existing=True,
    )
    logger.info("Triggered restore for stack %d from %s", stack_id, backup_filename)
