import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import get_current_user
from database import BackupJob, Destination, get_db
from docker_ops import list_containers, list_volumes
from encryption import decrypt, encrypt
from scheduler import add_backup_job, get_next_run_time, remove_backup_job, trigger_now, trigger_job_restore
from storage import list_backups

router = APIRouter()


class VolumeEntry(BaseModel):
    source: str
    name: str


class RestoreJobRequest(BaseModel):
    backup_filename: str
    containers_to_start: list[str] = []
    restore_volumes: bool = True
    restore_db: bool = True


class CreateJobRequest(BaseModel):
    name: str
    containers: list[str] = []
    volumes: list[dict[str, str]] = []
    db_type: Optional[str] = None
    db_container: Optional[str] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    destination_id: int
    schedule_cron: str
    pre_stop: bool = False
    retention_days: int = 30
    enabled: bool = True


@router.get("/containers")
def get_containers(current_user=Depends(get_current_user)):
    return list_containers()


@router.get("/volumes")
def get_volumes(current_user=Depends(get_current_user)):
    return list_volumes()


@router.get("")
def list_jobs(current_user=Depends(get_current_user), db=Depends(get_db)):
    jobs = db.query(BackupJob).all()
    result = []
    for job in jobs:
        next_run = get_next_run_time(job.id)
        result.append(
            {
                "id": job.id,
                "name": job.name,
                "containers": json.loads(job.containers or "[]"),
                "volumes": json.loads(job.volumes or "[]"),
                "db_type": job.db_type,
                "db_container": job.db_container,
                "db_name": job.db_name,
                "db_user": job.db_user,
                "destination_id": job.destination_id,
                "schedule_cron": job.schedule_cron,
                "pre_stop": job.pre_stop,
                "retention_days": job.retention_days,
                "enabled": job.enabled,
                "created_at": job.created_at.isoformat(),
                "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
                "last_run_status": job.last_run_status,
                "next_run": next_run,
            }
        )
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
def create_job(
    req: CreateJobRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    db_password_encrypted = None
    if req.db_password:
        db_password_encrypted = encrypt(req.db_password)

    job = BackupJob(
        name=req.name,
        containers=json.dumps(req.containers),
        volumes=json.dumps(req.volumes),
        db_type=req.db_type or None,
        db_container=req.db_container or None,
        db_name=req.db_name or None,
        db_user=req.db_user or None,
        db_password_encrypted=db_password_encrypted,
        destination_id=req.destination_id,
        schedule_cron=req.schedule_cron,
        pre_stop=req.pre_stop,
        retention_days=req.retention_days,
        enabled=req.enabled,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if job.enabled:
        try:
            add_backup_job(job.id, job.name, job.schedule_cron)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job saved but scheduler registration failed: {exc}",
            )

    return {
        "id": job.id,
        "name": job.name,
        "schedule_cron": job.schedule_cron,
        "enabled": job.enabled,
        "created_at": job.created_at.isoformat(),
    }


@router.put("/{job_id}")
def update_job(
    job_id: int,
    req: CreateJobRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    remove_backup_job(job_id)

    # Keep existing password unless a new one is provided
    db_password_encrypted = job.db_password_encrypted
    if req.db_password:
        db_password_encrypted = encrypt(req.db_password)

    job.name = req.name
    job.containers = json.dumps(req.containers)
    job.volumes = json.dumps(req.volumes)
    job.db_type = req.db_type or None
    job.db_container = req.db_container or None
    job.db_name = req.db_name or None
    job.db_user = req.db_user or None
    job.db_password_encrypted = db_password_encrypted
    job.destination_id = req.destination_id
    job.schedule_cron = req.schedule_cron
    job.pre_stop = req.pre_stop
    job.retention_days = req.retention_days
    job.enabled = req.enabled
    db.commit()

    if job.enabled:
        try:
            add_backup_job(job.id, job.name, job.schedule_cron)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job updated but scheduler failed: {exc}",
            )

    return {"id": job.id, "name": job.name}


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    remove_backup_job(job_id)
    db.delete(job)
    db.commit()


@router.post("/{job_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_job_now(
    job_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    trigger_now(job_id)
    return {"message": f"Backup job {job.name} triggered"}


@router.patch("/{job_id}/toggle")
def toggle_job(
    job_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    job.enabled = not job.enabled
    db.commit()

    if job.enabled:
        try:
            add_backup_job(job.id, job.name, job.schedule_cron)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to register job: {exc}",
            )
    else:
        remove_backup_job(job_id)

    return {"id": job.id, "enabled": job.enabled}


@router.get("/{job_id}/backups")
def list_job_backups(
    job_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    dest_record = db.query(Destination).filter(Destination.id == job.destination_id).first()
    if not dest_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Destination not found")

    dest_config = json.loads(decrypt(dest_record.config_encrypted))
    remote_name = f"dest_{dest_record.id}"
    remote_path = dest_config.get("path", "").rstrip("/")

    backups = list_backups(remote_name, remote_path)
    # Filter to only archives that belong to this job
    safe_name = job.name.replace(" ", "_")
    job_backups = [b for b in backups if b["name"].startswith(safe_name + "_")]

    return {
        "job_id": job_id,
        "job_name": job.name,
        "containers": json.loads(job.containers or "[]"),
        "remote_path": remote_path,
        "backups": job_backups,
    }


@router.post("/{job_id}/restore", status_code=status.HTTP_202_ACCEPTED)
def restore_job(
    job_id: int,
    req: RestoreJobRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    trigger_job_restore(
        job_id=job_id,
        backup_filename=req.backup_filename,
        containers_to_start=req.containers_to_start,
        restore_volumes=req.restore_volumes,
        restore_db=req.restore_db,
    )
    return {"message": f"Restore triggered for job: {job.name}"}
