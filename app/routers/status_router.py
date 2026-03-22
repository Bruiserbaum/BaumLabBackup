import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import get_current_user
from database import BackupJob, BackupRun, StackRun, get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _job_run_dict(run: BackupRun) -> dict:
    return {
        "id": run.id,
        "kind": "job",
        "name": run.job_name,
        "run_type": getattr(run, "run_type", "backup"),
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "size_bytes": run.size_bytes,
        "error": run.error,
    }


def _stack_run_dict(run: StackRun) -> dict:
    return {
        "id": run.id,
        "kind": "stack",
        "name": run.stack_name,
        "run_type": run.run_type,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "size_bytes": run.size_bytes,
        "error": run.error,
    }


@router.get("")
def dashboard_summary(current_user=Depends(get_current_user), db=Depends(get_db)):
    total_jobs = db.query(BackupJob).count()
    enabled_jobs = db.query(BackupJob).filter(BackupJob.enabled == True).count()

    job_runs = db.query(BackupRun).all()
    try:
        stack_runs = db.query(StackRun).all()
    except Exception as exc:
        logger.warning("Could not query stack_runs (schema may need migration): %s", exc)
        stack_runs = []
    all_runs = [_job_run_dict(r) for r in job_runs] + [_stack_run_dict(r) for r in stack_runs]

    total_runs = len(all_runs)
    successful_runs = sum(1 for r in all_runs if r["status"] == "success")
    failed_runs = sum(1 for r in all_runs if r["status"] == "failed")
    running_runs = sum(1 for r in all_runs if r["status"] == "running")

    recent_runs = sorted(all_runs, key=lambda r: r["started_at"], reverse=True)[:10]

    return {
        "total_jobs": total_jobs,
        "enabled_jobs": enabled_jobs,
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "running_runs": running_runs,
        "recent_runs": recent_runs,
    }


@router.get("/runs")
def list_runs(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    job_q = db.query(BackupRun)
    stack_q = db.query(StackRun)
    if status is not None:
        job_q = job_q.filter(BackupRun.status == status)
        stack_q = stack_q.filter(StackRun.status == status)

    try:
        stack_items = [_stack_run_dict(r) for r in stack_q.all()]
    except Exception as exc:
        logger.warning("Could not query stack_runs: %s", exc)
        stack_items = []
    all_items = [_job_run_dict(r) for r in job_q.all()] + stack_items
    all_items.sort(key=lambda r: r["started_at"], reverse=True)

    total = len(all_items)
    offset = (page - 1) * page_size
    items = all_items[offset: offset + page_size]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/runs/stack/{run_id}")
def get_stack_run(
    run_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    run = db.query(StackRun).filter(StackRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Stack run not found")
    return {
        **_stack_run_dict(run),
        "log_lines": json.loads(run.log_lines or "[]"),
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    run = db.query(BackupRun).filter(BackupRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        **_job_run_dict(run),
        "log_lines": json.loads(run.log_lines or "[]"),
        "destination_path": run.destination_path,
    }
