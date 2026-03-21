"""Stack restore executor — downloads archive, decrypts .env, clones repo, restores volumes."""

import json
import logging
import os
import shutil
import subprocess
import tarfile
from datetime import datetime

import docker

from config import BACKUP_TMP_DIR
from database import Destination, SessionLocal, Stack, StackRun
from encryption import decrypt
from storage import download_file

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


def _extract_volume(volume_name: str, tar_path: str, vol_dir: str) -> bool:
    """
    Restore a Docker volume from a tar.gz using an ephemeral Alpine container.
    Creates the volume if it does not exist.  Wipes existing contents before
    extracting so the restore is clean.
    """
    try:
        client = docker.from_env()

        try:
            client.volumes.get(volume_name)
        except docker.errors.NotFound:
            client.volumes.create(volume_name)
            logger.info("Created volume %s", volume_name)

        tar_basename = os.path.basename(tar_path)
        client.containers.run(
            "alpine:latest",
            # Clear existing data first, then extract
            f"sh -c 'find /data -mindepth 1 -delete 2>/dev/null; tar xzf /backup/{tar_basename} -C /data'",
            volumes={
                volume_name: {"bind": "/data", "mode": "rw"},
                vol_dir: {"bind": "/backup", "mode": "ro"},
            },
            remove=True,
        )
        return True

    except Exception as exc:
        logger.error("_extract_volume %s failed: %s", volume_name, exc)
        return False


# ── Main executor ─────────────────────────────────────────────────────────────

def execute_stack_restore(
    stack_id: int,
    backup_filename: str,
    restore_target_dir: str,
    auto_start: bool = True,
) -> None:
    """
    Restore a stack from a backup archive stored on the stack's destination.

    backup_filename:    archive filename only (e.g. stack_baumlab_20260321_030000.tar.gz)
    restore_target_dir: absolute path where the repo will be cloned (e.g. /opt/baumlab)
    auto_start:         if True, run `docker compose up -d` after restoring volumes
    """
    db = SessionLocal()
    run_id: int | None = None
    tmp_dir: str | None = None

    try:
        stack = db.query(Stack).filter(Stack.id == stack_id).first()
        if not stack:
            logger.warning("execute_stack_restore: stack %d not found", stack_id)
            return

        run = StackRun(
            stack_id=stack.id,
            stack_name=stack.name,
            run_type="restore",
            status="running",
            started_at=datetime.utcnow(),
            log_lines="[]",
            backup_path=backup_filename,
            restore_target=restore_target_dir,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        _log(run_id, f"Starting restore: {stack.name}", db)
        _log(run_id, f"Archive: {backup_filename}", db)
        _log(run_id, f"Target: {restore_target_dir}", db)

        # ── Resolve destination ───────────────────────────────────────────────
        dest_record = db.query(Destination).filter(Destination.id == stack.destination_id).first()
        if not dest_record:
            raise RuntimeError(f"Destination {stack.destination_id} not found")

        dest_config = json.loads(decrypt(dest_record.config_encrypted))
        remote_name = f"dest_{dest_record.id}"
        base_path = dest_config.get("path", "").rstrip("/")
        safe_name = stack.name.replace(" ", "_")
        remote_dir = f"{base_path}/stacks/{safe_name}" if base_path else f"stacks/{safe_name}"
        remote_file = f"{remote_dir}/{backup_filename}"

        # ── Download archive ──────────────────────────────────────────────────
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        tmp_dir = os.path.join(BACKUP_TMP_DIR, f"restore_{safe_name}_{timestamp}")
        os.makedirs(tmp_dir, exist_ok=True)

        local_archive = os.path.join(tmp_dir, backup_filename)
        _log(run_id, f"Downloading from {dest_record.name}...", db)
        ok, msg = download_file(remote_name, remote_file, local_archive)
        if not ok:
            raise RuntimeError(f"Download failed: {msg}")
        _log(run_id, "Download complete.", db)

        # ── Extract outer archive ─────────────────────────────────────────────
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        _log(run_id, "Extracting archive...", db)
        with tarfile.open(local_archive, "r:gz") as tar:
            tar.extractall(path=extract_dir)

        contents = os.listdir(extract_dir)
        if not contents:
            raise RuntimeError("Archive is empty — nothing to restore")
        inner_dir = os.path.join(extract_dir, contents[0])

        # ── Parse manifest ────────────────────────────────────────────────────
        manifest_path = os.path.join(inner_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise RuntimeError("manifest.json not found — archive may be corrupt or from an older version")
        with open(manifest_path) as fh:
            manifest = json.load(fh)

        _log(run_id, f"Manifest: {manifest.get('stack_name')} backed up at {manifest.get('backed_up_at')}", db)

        repo_url = manifest.get("repo_url") or stack.repo_url
        branch = manifest.get("repo_branch") or stack.repo_branch or "main"
        vol_entries: list[dict] = manifest.get("volumes", [])

        # ── Decrypt .env ──────────────────────────────────────────────────────
        env_enc_rel = manifest.get("env_file", "env/dot-env.enc")
        env_enc_path = os.path.join(inner_dir, env_enc_rel)
        decrypted_env: str | None = None
        if os.path.isfile(env_enc_path):
            _log(run_id, "Decrypting .env...", db)
            with open(env_enc_path) as fh:
                decrypted_env = decrypt(fh.read())
            _log(run_id, ".env decrypted OK.", db)
        else:
            _log(run_id, "WARNING: encrypted .env not found in archive — continuing without it", db)

        # ── Git clone / pull ──────────────────────────────────────────────────
        _log(run_id, f"Cloning {repo_url} (branch: {branch}) → {restore_target_dir}", db)
        if os.path.isdir(os.path.join(restore_target_dir, ".git")):
            _log(run_id, "Directory already a git repo — pulling latest...", db)
            result = subprocess.run(
                ["git", "-C", restore_target_dir, "pull", "--ff-only"],
                capture_output=True, text=True, timeout=120,
            )
        else:
            os.makedirs(restore_target_dir, exist_ok=True)
            result = subprocess.run(
                ["git", "clone", "--branch", branch, "--depth", "1", repo_url, restore_target_dir],
                capture_output=True, text=True, timeout=300,
            )

        if result.returncode != 0:
            raise RuntimeError(f"git failed (exit {result.returncode}): {result.stderr.strip()}")
        _log(run_id, "Repository ready.", db)

        # ── Write .env ────────────────────────────────────────────────────────
        if decrypted_env is not None:
            env_dest = os.path.join(restore_target_dir, ".env")
            with open(env_dest, "w", encoding="utf-8") as fh:
                fh.write(decrypted_env)
            _log(run_id, f".env written to {env_dest}", db)

        # ── Restore volumes ───────────────────────────────────────────────────
        vol_dir = os.path.join(inner_dir, "volumes")
        _log(run_id, f"Restoring {len(vol_entries)} volume(s)...", db)
        for entry in vol_entries:
            vol_name = entry["name"]
            tar_path = os.path.join(inner_dir, entry["archive"])
            if not os.path.isfile(tar_path):
                _log(run_id, f"  WARNING: archive missing for volume {vol_name} — skipping", db)
                continue
            _log(run_id, f"  Restoring: {vol_name}", db)
            if _extract_volume(vol_name, tar_path, vol_dir):
                _log(run_id, f"  OK: {vol_name}", db)
            else:
                _log(run_id, f"  WARNING: failed to restore {vol_name}", db)

        # ── Docker Compose up ─────────────────────────────────────────────────
        if auto_start:
            _log(run_id, "Running: docker compose up -d --pull always", db)
            result = subprocess.run(
                ["docker", "compose", "up", "-d", "--pull", "always"],
                capture_output=True, text=True, timeout=600,
                cwd=restore_target_dir,
                env={**os.environ, "DOCKER_HOST": "unix:///var/run/docker.sock"},
            )
            if result.returncode == 0:
                _log(run_id, "Stack started successfully.", db)
                if result.stdout.strip():
                    for line in result.stdout.strip().splitlines():
                        _log(run_id, f"  {line}", db)
            else:
                err = (result.stderr or result.stdout).strip()
                _log(run_id, f"WARNING: docker compose up returned {result.returncode}: {err}", db)
        else:
            _log(run_id, f"Auto-start skipped. Start manually: cd {restore_target_dir} && docker compose up -d", db)

        # ── Success ───────────────────────────────────────────────────────────
        run = db.query(StackRun).filter(StackRun.id == run_id).first()
        run.status = "success"
        run.completed_at = datetime.utcnow()
        db.commit()

        _log(run_id, "Restore completed successfully.", db)

    except Exception as exc:
        logger.exception("execute_stack_restore %d failed: %s", stack_id, exc)
        if run_id:
            try:
                run = db.query(StackRun).filter(StackRun.id == run_id).first()
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
