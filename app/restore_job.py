"""Backup-job restore executor — downloads archive, restores volumes and DB, starts containers."""

import json
import logging
import os
import shutil
import tarfile
from datetime import datetime

import docker

from config import BACKUP_TMP_DIR
from database import BackupJob, BackupRun, Destination, SessionLocal
from docker_ops import run_db_restore, start_container
from encryption import decrypt
from storage import download_file

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(run_id: int, text: str, db) -> None:
    run = db.query(BackupRun).filter(BackupRun.id == run_id).first()
    if not run:
        return
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = json.loads(run.log_lines or "[]")
    lines.append(f"[{ts}] {text}")
    run.log_lines = json.dumps(lines)
    db.commit()


def _restore_named_volume(volume_name: str, tar_path: str, vol_dir: str) -> bool:
    """
    Restore a named Docker volume from a tar.gz using an ephemeral Alpine container.
    Creates the volume if it doesn't exist; wipes existing data before extracting.
    """
    try:
        client = docker.from_env()
        try:
            client.volumes.get(volume_name)
        except docker.errors.NotFound:
            client.volumes.create(volume_name)
            logger.info("Created volume %s for restore", volume_name)

        tar_basename = os.path.basename(tar_path)
        client.containers.run(
            "alpine:latest",
            f"sh -c 'find /data -mindepth 1 -delete 2>/dev/null; tar xzf /backup/{tar_basename} -C /data'",
            volumes={
                volume_name: {"bind": "/data", "mode": "rw"},
                vol_dir: {"bind": "/backup", "mode": "ro"},
            },
            remove=True,
        )
        return True
    except Exception as exc:
        logger.error("_restore_named_volume %s failed: %s", volume_name, exc)
        return False


# ── Main executor ─────────────────────────────────────────────────────────────

def execute_job_restore(
    job_id: int,
    backup_filename: str,
    containers_to_start: list[str],
    restore_volumes: bool = True,
    restore_db: bool = True,
) -> None:
    """
    Restore a backup job archive.

    backup_filename:     archive filename only (e.g. Authentik_Full_Backup_20260322_212931.tar.gz)
    containers_to_start: list of container names to start after restore (may be empty)
    restore_volumes:     whether to restore named Docker volumes from the archive
    restore_db:          whether to restore the DB dump if one exists in the archive
    """
    db = SessionLocal()
    run_id: int | None = None
    tmp_dir: str | None = None

    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        if not job:
            logger.warning("execute_job_restore: job %d not found", job_id)
            return

        run = BackupRun(
            job_id=job.id,
            job_name=job.name,
            run_type="restore",
            status="running",
            started_at=datetime.utcnow(),
            log_lines="[]",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        _log(run_id, f"Starting restore: {job.name}", db)
        _log(run_id, f"Archive: {backup_filename}", db)

        # ── Resolve destination ───────────────────────────────────────────────
        dest_record = db.query(Destination).filter(Destination.id == job.destination_id).first()
        if not dest_record:
            raise RuntimeError(f"Destination {job.destination_id} not found")

        dest_config = json.loads(decrypt(dest_record.config_encrypted))
        remote_name = f"dest_{dest_record.id}"
        remote_path = dest_config.get("path", "").rstrip("/")
        remote_file = f"{remote_path}/{backup_filename}" if remote_path else backup_filename

        # ── Download ──────────────────────────────────────────────────────────
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_name = job.name.replace(" ", "_")
        tmp_dir = os.path.join(BACKUP_TMP_DIR, f"restore_{safe_name}_{timestamp}")
        os.makedirs(tmp_dir, exist_ok=True)

        local_archive = os.path.join(tmp_dir, backup_filename)
        _log(run_id, f"Downloading from {dest_record.name} ({dest_record.type})...", db)
        ok, msg = download_file(remote_name, remote_file, local_archive)
        if not ok:
            raise RuntimeError(f"Download failed: {msg}")
        _log(run_id, f"Downloaded {os.path.getsize(local_archive):,} bytes.", db)

        # ── Extract ───────────────────────────────────────────────────────────
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        _log(run_id, "Extracting archive...", db)
        with tarfile.open(local_archive, "r:gz") as tar:
            tar.extractall(path=extract_dir)

        contents = os.listdir(extract_dir)
        if not contents:
            raise RuntimeError("Archive is empty")
        inner_dir = os.path.join(extract_dir, contents[0])

        # ── Restore named volumes ─────────────────────────────────────────────
        vol_dir = os.path.join(inner_dir, "volumes")
        if restore_volumes and os.path.isdir(vol_dir):
            vol_archives = [f for f in os.listdir(vol_dir) if f.endswith(".tar.gz")]
            _log(run_id, f"Restoring {len(vol_archives)} volume(s)...", db)
            for fname in vol_archives:
                vol_name = fname[:-len(".tar.gz")]  # strip .tar.gz
                tar_path = os.path.join(vol_dir, fname)
                _log(run_id, f"  Restoring volume: {vol_name}", db)
                if _restore_named_volume(vol_name, tar_path, vol_dir):
                    _log(run_id, f"  OK: {vol_name}", db)
                else:
                    _log(run_id, f"  WARNING: failed to restore {vol_name}", db)
        elif restore_volumes:
            _log(run_id, "No volumes/ directory in archive — skipping volume restore.", db)

        # ── Restore DB dump ───────────────────────────────────────────────────
        if restore_db and job.db_type and job.db_type.lower() not in ("none", ""):
            sql_files = [
                f for f in os.listdir(inner_dir)
                if f.endswith(".sql")
            ]
            if sql_files:
                sql_path = os.path.join(inner_dir, sql_files[0])
                _log(run_id, f"Restoring {job.db_type} dump: {sql_files[0]}...", db)
                db_password = ""
                if job.db_password_encrypted:
                    db_password = decrypt(job.db_password_encrypted)
                ok = run_db_restore(
                    container_name=job.db_container or "",
                    db_type=job.db_type,
                    db_name=job.db_name or "",
                    db_user=job.db_user or "",
                    db_password=db_password,
                    sql_path=sql_path,
                )
                if ok:
                    _log(run_id, "  DB restore complete.", db)
                else:
                    _log(run_id, "  WARNING: DB restore failed — container may not be running.", db)
            else:
                _log(run_id, "No .sql file found in archive — skipping DB restore.", db)

        # ── Start containers ──────────────────────────────────────────────────
        if containers_to_start:
            _log(run_id, f"Starting {len(containers_to_start)} container(s)...", db)
            for cname in containers_to_start:
                if start_container(cname):
                    _log(run_id, f"  Started: {cname}", db)
                else:
                    _log(run_id, f"  WARNING: could not start {cname}", db)
        else:
            _log(run_id, "No containers to start — restore complete.", db)

        # ── Success ───────────────────────────────────────────────────────────
        run = db.query(BackupRun).filter(BackupRun.id == run_id).first()
        run.status = "success"
        run.completed_at = datetime.utcnow()
        db.commit()
        _log(run_id, "Restore completed successfully.", db)

    except Exception as exc:
        logger.exception("execute_job_restore %d failed: %s", job_id, exc)
        if run_id:
            try:
                run = db.query(BackupRun).filter(BackupRun.id == run_id).first()
                if run:
                    run.status = "failed"
                    run.completed_at = datetime.utcnow()
                    run.error = str(exc)
                    db.commit()
                _log(run_id, f"ERROR: {exc}", db)
            except Exception:
                pass

    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        db.close()
