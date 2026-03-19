import json
import logging
import os
import shutil
import tarfile
from datetime import datetime
from typing import Optional

from database import BackupJob, BackupRun, Destination, SessionLocal
from docker_ops import run_db_dump, start_container, stop_container
from encryption import decrypt
from config import BACKUP_TMP_DIR
from storage import delete_old_backups, upload

logger = logging.getLogger(__name__)


def log_line(run_id: int, text: str, db) -> None:
    run = db.query(BackupRun).filter(BackupRun.id == run_id).first()
    if not run:
        return
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = json.loads(run.log_lines or "[]")
    lines.append(f"[{timestamp}] {text}")
    run.log_lines = json.dumps(lines)
    db.commit()


def execute_backup_job(job_id: int) -> None:
    db = SessionLocal()
    run_id: Optional[int] = None
    stopped_containers: list[str] = []
    tmp_dir: Optional[str] = None
    archive_path: Optional[str] = None

    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        if not job:
            logger.warning("execute_backup_job: job %d not found", job_id)
            return
        if not job.enabled:
            logger.info("execute_backup_job: job %d is disabled, skipping", job_id)
            return

        # Create run record
        run = BackupRun(
            job_id=job.id,
            job_name=job.name,
            status="running",
            started_at=datetime.utcnow(),
            log_lines="[]",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        log_line(run_id, f"Starting backup job: {job.name}", db)

        containers = json.loads(job.containers or "[]")
        volumes = json.loads(job.volumes or "[]")

        # Stop containers if pre_stop is enabled
        if job.pre_stop and containers:
            log_line(run_id, f"Stopping {len(containers)} container(s)...", db)
            for cname in containers:
                if stop_container(cname):
                    stopped_containers.append(cname)
                    log_line(run_id, f"  Stopped: {cname}", db)
                else:
                    log_line(run_id, f"  Warning: could not stop {cname}", db)

        # Create temp directory
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        tmp_dir = os.path.join(BACKUP_TMP_DIR, f"{job.name}_{timestamp}")
        os.makedirs(tmp_dir, exist_ok=True)
        log_line(run_id, f"Using temp dir: {tmp_dir}", db)

        # Copy volumes
        if volumes:
            vol_dir = os.path.join(tmp_dir, "volumes")
            os.makedirs(vol_dir, exist_ok=True)
            log_line(run_id, f"Copying {len(volumes)} volume(s)...", db)
            for vol in volumes:
                source = vol.get("source", "")
                name = vol.get("name", os.path.basename(source))
                dest = os.path.join(vol_dir, name)
                if not source or not os.path.exists(source):
                    log_line(run_id, f"  Warning: source not found: {source}", db)
                    continue
                if os.path.isdir(source):
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)
                log_line(run_id, f"  Copied: {source} -> {dest}", db)

        # Database dump
        if job.db_type and job.db_type.lower() not in ("none", ""):
            log_line(run_id, f"Running {job.db_type} dump for {job.db_name}...", db)
            db_password = ""
            if job.db_password_encrypted:
                db_password = decrypt(job.db_password_encrypted)
            dump_filename = f"db_{job.db_name}_{timestamp}.sql"
            dump_path = os.path.join(tmp_dir, dump_filename)
            success = run_db_dump(
                container_name=job.db_container or "",
                db_type=job.db_type,
                db_name=job.db_name or "",
                db_user=job.db_user or "",
                db_password=db_password,
                output_path=dump_path,
            )
            if success:
                log_line(run_id, f"  DB dump written to {dump_path}", db)
            else:
                log_line(run_id, "  Warning: DB dump failed", db)

        # Create tar.gz archive
        archive_path = os.path.join(BACKUP_TMP_DIR, f"{job.name}_{timestamp}.tar.gz")
        log_line(run_id, f"Creating archive: {archive_path}", db)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_dir, arcname=os.path.basename(tmp_dir))

        archive_size = os.path.getsize(archive_path)
        log_line(run_id, f"Archive size: {archive_size} bytes", db)

        # Get destination
        dest_record = db.query(Destination).filter(Destination.id == job.destination_id).first()
        if not dest_record:
            raise RuntimeError(f"Destination {job.destination_id} not found")

        dest_config = json.loads(decrypt(dest_record.config_encrypted))
        remote_name = f"dest_{dest_record.id}"
        remote_path = dest_config.get("path", "")

        log_line(run_id, f"Uploading to {dest_record.name} ({dest_record.type})...", db)
        ok, msg = upload(archive_path, remote_name, remote_path)
        if not ok:
            raise RuntimeError(f"Upload failed: {msg}")
        log_line(run_id, "Upload complete.", db)

        # Retention cleanup
        if job.retention_days and job.retention_days > 0:
            log_line(run_id, f"Applying retention: deleting files older than {job.retention_days} days...", db)
            delete_old_backups(remote_name, remote_path, job.retention_days)

        destination_path = f"{remote_name}:{remote_path}"

        # Update run record — success
        run = db.query(BackupRun).filter(BackupRun.id == run_id).first()
        run.status = "success"
        run.completed_at = datetime.utcnow()
        run.size_bytes = archive_size
        run.destination_path = destination_path
        db.commit()

        # Update job last_run
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        if job:
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "success"
            db.commit()

        log_line(run_id, "Backup job completed successfully.", db)

    except Exception as exc:
        logger.exception("execute_backup_job %d failed: %s", job_id, exc)
        if run_id:
            try:
                run = db.query(BackupRun).filter(BackupRun.id == run_id).first()
                if run:
                    run.status = "failed"
                    run.completed_at = datetime.utcnow()
                    run.error = str(exc)
                    db.commit()
                log_line(run_id, f"ERROR: {exc}", db)

                job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
                if job:
                    job.last_run_at = datetime.utcnow()
                    job.last_run_status = "failed"
                    db.commit()
            except Exception:
                logger.exception("Failed to update run record after error")

    finally:
        # Restart any stopped containers
        for cname in stopped_containers:
            try:
                start_container(cname)
                if run_id:
                    log_line(run_id, f"Restarted container: {cname}", db)
            except Exception as exc:
                logger.error("Failed to restart container %s: %s", cname, exc)

        # Cleanup temp files
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if archive_path and os.path.exists(archive_path):
            os.remove(archive_path)

        db.close()
