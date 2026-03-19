import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import get_current_user
from database import BackupJob, BackupRun, get_db

router = APIRouter()


@router.get("/")
def dashboard_summary(current_user=Depends(get_current_user), db=Depends(get_db)):
    total_jobs = db.query(BackupJob).count()
    enabled_jobs = db.query(BackupJob).filter(BackupJob.enabled == True).count()
    total_runs = db.query(BackupRun).count()
    successful_runs = db.query(BackupRun).filter(BackupRun.status == "success").count()
    failed_runs = db.query(BackupRun).filter(BackupRun.status == "failed").count()
    running_runs = db.query(BackupRun).filter(BackupRun.status == "running").count()

    recent_runs_q = (
        db.query(BackupRun)
        .order_by(BackupRun.started_at.desc())
        .limit(10)
        .all()
    )

    recent_runs = []
    for run in recent_runs_q:
        recent_runs.append(
            {
                "id": run.id,
                "job_id": run.job_id,
                "job_name": run.job_name,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "size_bytes": run.size_bytes,
                "destination_path": run.destination_path,
                "error": run.error,
            }
        )

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
    job_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = db.query(BackupRun)
    if job_id is not None:
        q = q.filter(BackupRun.job_id == job_id)
    if status is not None:
        q = q.filter(BackupRun.status == status)

    total = q.count()
    runs = q.order_by(BackupRun.started_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for run in runs:
        items.append(
            {
                "id": run.id,
                "job_id": run.job_id,
                "job_name": run.job_name,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "size_bytes": run.size_bytes,
                "destination_path": run.destination_path,
                "error": run.error,
            }
        )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
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

    log_lines = json.loads(run.log_lines or "[]")

    return {
        "id": run.id,
        "job_id": run.job_id,
        "job_name": run.job_name,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "size_bytes": run.size_bytes,
        "destination_path": run.destination_path,
        "log_lines": log_lines,
        "error": run.error,
    }
