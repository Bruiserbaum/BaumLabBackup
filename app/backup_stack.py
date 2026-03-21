"""Stack backup executor — archives Docker volumes + encrypted .env + manifest."""

import json
import logging
import os
import shutil
import tarfile
from datetime import datetime

import docker

from config import BACKUP_TMP_DIR
from database import Destination, SessionLocal, Stack, StackRun
from encryption import decrypt, encrypt
from storage import delete_old_backups, upload

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(run_id: int, text: str, db) -> None:
    run = db.query(StackRun).filter(StackRun.id == run_id).first()
    if not run:
        return
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = json.loads(run.log_lines or "[]")
    lines.append(f"[{ts}] {text}")
    run.log_lines = json.dumps(lines)
    db.commit()


def _tar_volume(volume_name: str, vol_dir: str) -> bool:
    """
    Tar a Docker volume's contents into vol_dir/{volume_name}.tar.gz using an
    ephemeral Alpine container.  The volume is mounted read-only so live data
    is never modified.
    """
    try:
        client = docker.from_env()
        client.containers.run(
            "alpine:latest",
            f"tar czf /backup/{volume_name}.tar.gz -C /data .",
            volumes={
                volume_name: {"bind": "/data", "mode": "ro"},
                vol_dir: {"bind": "/backup", "mode": "rw"},
            },
            remove=True,
        )
        return True
    except Exception as exc:
        logger.error("_tar_volume %s failed: %s", volume_name, exc)
        return False


# ── Main executor ─────────────────────────────────────────────────────────────

def execute_stack_backup(stack_id: int) -> None:
    db = SessionLocal()
    run_id: int | None = None
    tmp_dir: str | None = None
    archive_path: str | None = None

    try:
        stack = db.query(Stack).filter(Stack.id == stack_id).first()
        if not stack:
            logger.warning("execute_stack_backup: stack %d not found", stack_id)
            return
        if not stack.enabled:
            logger.info("execute_stack_backup: stack %d disabled, skipping", stack_id)
            return

        # Create run record
        run = StackRun(
            stack_id=stack.id,
            stack_name=stack.name,
            run_type="backup",
            status="running",
            started_at=datetime.utcnow(),
            log_lines="[]",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        _log(run_id, f"Starting stack backup: {stack.name}", db)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_name = stack.name.replace(" ", "_")
        tmp_dir = os.path.join(BACKUP_TMP_DIR, f"stack_{safe_name}_{timestamp}")
        os.makedirs(tmp_dir, exist_ok=True)

        volumes = json.loads(stack.volumes or "[]")

        # ── Archive volumes ───────────────────────────────────────────────────
        vol_dir = os.path.join(tmp_dir, "volumes")
        os.makedirs(vol_dir, exist_ok=True)
        _log(run_id, f"Archiving {len(volumes)} volume(s)...", db)
        for vol_name in volumes:
            _log(run_id, f"  Volume: {vol_name}", db)
            if _tar_volume(vol_name, vol_dir):
                size = os.path.getsize(os.path.join(vol_dir, f"{vol_name}.tar.gz"))
                _log(run_id, f"  OK — {size:,} bytes", db)
            else:
                _log(run_id, f"  WARNING: failed to archive {vol_name}", db)

        # ── Encrypt .env ──────────────────────────────────────────────────────
        env_dir = os.path.join(tmp_dir, "env")
        os.makedirs(env_dir, exist_ok=True)
        if stack.env_path and os.path.isfile(stack.env_path):
            _log(run_id, f"Encrypting .env from {stack.env_path}...", db)
            with open(stack.env_path, "r", encoding="utf-8") as fh:
                env_content = fh.read()
            encrypted_env = encrypt(env_content)
            with open(os.path.join(env_dir, "dot-env.enc"), "w") as fh:
                fh.write(encrypted_env)
            _log(run_id, "  .env encrypted OK.", db)
        else:
            _log(run_id, f"  WARNING: .env not found at {stack.env_path!r} — skipping", db)

        # ── Write manifest ────────────────────────────────────────────────────
        manifest = {
            "version": "1",
            "stack_name": stack.name,
            "compose_project": stack.compose_project,
            "repo_url": stack.repo_url,
            "repo_branch": stack.repo_branch,
            "backed_up_at": datetime.utcnow().isoformat(),
            "volumes": [{"name": v, "archive": f"volumes/{v}.tar.gz"} for v in volumes],
            "env_file": "env/dot-env.enc",
        }
        with open(os.path.join(tmp_dir, "manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)
        _log(run_id, "Manifest written.", db)

        # ── Outer tar.gz ──────────────────────────────────────────────────────
        archive_name = f"stack_{safe_name}_{timestamp}.tar.gz"
        archive_path = os.path.join(BACKUP_TMP_DIR, archive_name)
        _log(run_id, "Creating archive...", db)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_dir, arcname=os.path.basename(tmp_dir))
        archive_size = os.path.getsize(archive_path)
        _log(run_id, f"Archive: {archive_size:,} bytes", db)

        # ── Upload ────────────────────────────────────────────────────────────
        dest_record = db.query(Destination).filter(Destination.id == stack.destination_id).first()
        if not dest_record:
            raise RuntimeError(f"Destination {stack.destination_id} not found")

        from encryption import decrypt as _dec
        dest_config = json.loads(_dec(dest_record.config_encrypted))
        remote_name = f"dest_{dest_record.id}"
        base_path = dest_config.get("path", "").rstrip("/")
        remote_path = f"{base_path}/stacks/{safe_name}" if base_path else f"stacks/{safe_name}"

        _log(run_id, f"Uploading to {dest_record.name} ({dest_record.type})...", db)
        ok, msg = upload(archive_path, remote_name, remote_path)
        if not ok:
            raise RuntimeError(f"Upload failed: {msg}")
        _log(run_id, "Upload complete.", db)

        # ── Retention ─────────────────────────────────────────────────────────
        if stack.retention_days and stack.retention_days > 0:
            _log(run_id, f"Applying retention: {stack.retention_days} days...", db)
            delete_old_backups(remote_name, remote_path, stack.retention_days)

        # ── Finalise ──────────────────────────────────────────────────────────
        run = db.query(StackRun).filter(StackRun.id == run_id).first()
        run.status = "success"
        run.completed_at = datetime.utcnow()
        run.size_bytes = archive_size
        run.backup_path = f"{remote_name}:{remote_path}/{archive_name}"
        db.commit()

        stack = db.query(Stack).filter(Stack.id == stack_id).first()
        if stack:
            stack.last_backup_at = datetime.utcnow()
            stack.last_backup_status = "success"
            db.commit()

        _log(run_id, "Stack backup completed successfully.", db)

    except Exception as exc:
        logger.exception("execute_stack_backup %d failed: %s", stack_id, exc)
        if run_id:
            try:
                run = db.query(StackRun).filter(StackRun.id == run_id).first()
                if run:
                    run.status = "failed"
                    run.completed_at = datetime.utcnow()
                    run.error = str(exc)
                    db.commit()
                _log(run_id, f"ERROR: {exc}", db)
                stack = db.query(Stack).filter(Stack.id == stack_id).first()
                if stack:
                    stack.last_backup_at = datetime.utcnow()
                    stack.last_backup_status = "failed"
                    db.commit()
            except Exception:
                pass

    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if archive_path and os.path.exists(archive_path):
            try:
                os.remove(archive_path)
            except OSError:
                pass
        db.close()
