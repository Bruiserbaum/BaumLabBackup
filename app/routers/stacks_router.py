import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import get_current_user
from database import Destination, Stack, StackRun, get_db
from docker_ops import detect_compose_stacks, list_volumes
from encryption import decrypt
from scheduler import (
    add_stack_job,
    get_stack_next_run_time,
    remove_stack_job,
    trigger_stack_now,
)
from storage import list_backups

router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────

class CreateStackRequest(BaseModel):
    name: str
    repo_url: str
    repo_branch: str = "main"
    env_path: str = ""
    compose_project: str
    volumes: list[str] = []
    destination_id: int
    schedule_cron: Optional[str] = None
    retention_days: int = 30
    enabled: bool = True


class RestoreRequest(BaseModel):
    backup_filename: str
    restore_target_dir: str
    auto_start: bool = True


# ── Stack CRUD ────────────────────────────────────────────────────────────────

@router.get("")
def list_stacks(current_user=Depends(get_current_user), db=Depends(get_db)):
    stacks = db.query(Stack).all()
    result = []
    for s in stacks:
        next_run = get_stack_next_run_time(s.id) if s.schedule_cron else None
        result.append({
            "id": s.id,
            "name": s.name,
            "repo_url": s.repo_url,
            "repo_branch": s.repo_branch,
            "env_path": s.env_path,
            "compose_project": s.compose_project,
            "volumes": json.loads(s.volumes or "[]"),
            "destination_id": s.destination_id,
            "schedule_cron": s.schedule_cron,
            "retention_days": s.retention_days,
            "enabled": s.enabled,
            "created_at": s.created_at.isoformat(),
            "last_backup_at": s.last_backup_at.isoformat() if s.last_backup_at else None,
            "last_backup_status": s.last_backup_status,
            "next_run": next_run,
        })
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
def create_stack(
    req: CreateStackRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    dest = db.query(Destination).filter(Destination.id == req.destination_id).first()
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    stack = Stack(
        name=req.name,
        repo_url=req.repo_url,
        repo_branch=req.repo_branch,
        env_path=req.env_path,
        compose_project=req.compose_project,
        volumes=json.dumps(req.volumes),
        destination_id=req.destination_id,
        schedule_cron=req.schedule_cron or None,
        retention_days=req.retention_days,
        enabled=req.enabled,
    )
    db.add(stack)
    db.commit()
    db.refresh(stack)

    if stack.enabled and stack.schedule_cron:
        try:
            add_stack_job(stack.id, stack.name, stack.schedule_cron)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Stack saved but scheduler registration failed: {exc}",
            )

    return {"id": stack.id, "name": stack.name}


@router.put("/{stack_id}")
def update_stack(
    stack_id: int,
    req: CreateStackRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    stack = db.query(Stack).filter(Stack.id == stack_id).first()
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    remove_stack_job(stack_id)

    stack.name = req.name
    stack.repo_url = req.repo_url
    stack.repo_branch = req.repo_branch
    stack.env_path = req.env_path
    stack.compose_project = req.compose_project
    stack.volumes = json.dumps(req.volumes)
    stack.destination_id = req.destination_id
    stack.schedule_cron = req.schedule_cron or None
    stack.retention_days = req.retention_days
    stack.enabled = req.enabled
    db.commit()

    if stack.enabled and stack.schedule_cron:
        try:
            add_stack_job(stack.id, stack.name, stack.schedule_cron)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Updated but scheduler failed: {exc}")

    return {"id": stack.id, "name": stack.name}


@router.delete("/{stack_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stack(
    stack_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    stack = db.query(Stack).filter(Stack.id == stack_id).first()
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")
    remove_stack_job(stack_id)
    db.delete(stack)
    db.commit()


@router.patch("/{stack_id}/toggle")
def toggle_stack(
    stack_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    stack = db.query(Stack).filter(Stack.id == stack_id).first()
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    stack.enabled = not stack.enabled
    db.commit()

    if stack.enabled and stack.schedule_cron:
        try:
            add_stack_job(stack.id, stack.name, stack.schedule_cron)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to register job: {exc}")
    else:
        remove_stack_job(stack_id)

    return {"id": stack.id, "enabled": stack.enabled}


# ── Detection ─────────────────────────────────────────────────────────────────

@router.get("/detect")
def detect_stacks(current_user=Depends(get_current_user)):
    """Detect running Docker Compose stacks from container labels (Portainer-compatible)."""
    return detect_compose_stacks()


@router.get("/volumes")
def get_volumes(current_user=Depends(get_current_user)):
    return list_volumes()


# ── Backup ────────────────────────────────────────────────────────────────────

@router.post("/{stack_id}/backup", status_code=status.HTTP_202_ACCEPTED)
def backup_stack_now(
    stack_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    stack = db.query(Stack).filter(Stack.id == stack_id).first()
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")
    trigger_stack_now(stack_id)
    return {"message": f"Backup triggered for stack: {stack.name}"}


# ── Browse backups ────────────────────────────────────────────────────────────

@router.get("/{stack_id}/backups")
def list_stack_backups(
    stack_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    stack = db.query(Stack).filter(Stack.id == stack_id).first()
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    dest_record = db.query(Destination).filter(Destination.id == stack.destination_id).first()
    if not dest_record:
        raise HTTPException(status_code=404, detail="Destination not found")

    dest_config = json.loads(decrypt(dest_record.config_encrypted))
    remote_name = f"dest_{dest_record.id}"
    base_path = dest_config.get("path", "").rstrip("/")
    safe_name = stack.name.replace(" ", "_")
    remote_path = f"{base_path}/stacks/{safe_name}" if base_path else f"stacks/{safe_name}"

    backups = list_backups(remote_name, remote_path)
    return {"stack_id": stack_id, "remote_path": remote_path, "backups": backups}


# ── Restore ───────────────────────────────────────────────────────────────────

@router.post("/{stack_id}/restore", status_code=status.HTTP_202_ACCEPTED)
def restore_stack(
    stack_id: int,
    req: RestoreRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    stack = db.query(Stack).filter(Stack.id == stack_id).first()
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    from scheduler import trigger_stack_restore
    trigger_stack_restore(stack_id, req.backup_filename, req.restore_target_dir, req.auto_start)
    return {"message": f"Restore triggered for stack: {stack.name}"}


# ── Stack run history ─────────────────────────────────────────────────────────

@router.get("/runs")
def list_stack_runs(
    stack_id: Optional[int] = None,
    run_type: Optional[str] = None,
    page: int = 1,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    q = db.query(StackRun)
    if stack_id:
        q = q.filter(StackRun.stack_id == stack_id)
    if run_type:
        q = q.filter(StackRun.run_type == run_type)
    q = q.order_by(StackRun.started_at.desc())
    total = q.count()
    runs = q.offset((page - 1) * 20).limit(20).all()

    return {
        "total": total,
        "page": page,
        "runs": [_run_summary(r) for r in runs],
    }


@router.get("/runs/{run_id}")
def get_stack_run(
    run_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    run = db.query(StackRun).filter(StackRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        **_run_summary(run),
        "log_lines": json.loads(run.log_lines or "[]"),
        "error": run.error,
    }


def _run_summary(run: StackRun) -> dict:
    return {
        "id": run.id,
        "stack_id": run.stack_id,
        "stack_name": run.stack_name,
        "run_type": run.run_type,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "size_bytes": run.size_bytes,
        "backup_path": run.backup_path,
        "restore_target": run.restore_target,
    }
