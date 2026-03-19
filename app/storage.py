import configparser
import logging
import os
import subprocess
from typing import Optional

from config import RCLONE_CONFIG_PATH

logger = logging.getLogger(__name__)


def _rclone(*args: str) -> tuple[int, str, str]:
    cmd = ["rclone", "--config", RCLONE_CONFIG_PATH, *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "rclone command timed out after 3600s"
    except FileNotFoundError:
        return 1, "", "rclone binary not found"


def _obscure_password(password: str) -> str:
    rc, stdout, stderr = _rclone("obscure", password)
    if rc != 0:
        raise RuntimeError(f"rclone obscure failed: {stderr}")
    return stdout.strip()


def _write_remote_config(remote_name: str, config_entry: str) -> None:
    """Read existing rclone.conf, remove any existing section for remote_name, append new entry."""
    os.makedirs(os.path.dirname(RCLONE_CONFIG_PATH), exist_ok=True)

    existing = ""
    if os.path.exists(RCLONE_CONFIG_PATH):
        with open(RCLONE_CONFIG_PATH, "r") as fh:
            existing = fh.read()

    # Strip existing section for this remote
    lines = existing.splitlines(keepends=True)
    result_lines: list[str] = []
    inside_target = False
    for line in lines:
        stripped = line.strip()
        if stripped == f"[{remote_name}]":
            inside_target = True
            continue
        if inside_target and stripped.startswith("[") and stripped.endswith("]"):
            inside_target = False
        if not inside_target:
            result_lines.append(line)

    new_content = "".join(result_lines).rstrip("\n")
    if new_content:
        new_content += "\n\n"
    new_content += config_entry.strip() + "\n"

    with open(RCLONE_CONFIG_PATH, "w") as fh:
        fh.write(new_content)


def configure_b2(remote_name: str, account: str, key: str) -> None:
    entry = f"[{remote_name}]\ntype = b2\naccount = {account}\nkey = {key}\n"
    _write_remote_config(remote_name, entry)


def configure_smb(
    remote_name: str,
    host: str,
    share: str,
    user: str,
    password: str,
    domain: str,
) -> None:
    obscured = _obscure_password(password)
    entry = (
        f"[{remote_name}]\n"
        f"type = smb\n"
        f"host = {host}\n"
        f"share = {share}\n"
        f"user = {user}\n"
        f"pass = {obscured}\n"
        f"domain = {domain}\n"
    )
    _write_remote_config(remote_name, entry)


def configure_sftp(
    remote_name: str,
    host: str,
    port: int,
    user: str,
    password: Optional[str],
    key_file: Optional[str],
) -> None:
    lines = [
        f"[{remote_name}]",
        "type = sftp",
        f"host = {host}",
        f"port = {port}",
        f"user = {user}",
    ]
    if password:
        obscured = _obscure_password(password)
        lines.append(f"pass = {obscured}")
    if key_file:
        lines.append(f"key_file = {key_file}")
    entry = "\n".join(lines) + "\n"
    _write_remote_config(remote_name, entry)


def configure_local(remote_name: str, path: str) -> None:
    entry = f"[{remote_name}]\ntype = alias\nremote = {path}\n"
    _write_remote_config(remote_name, entry)


def upload(local_path: str, remote_name: str, remote_path: str) -> tuple[bool, str]:
    dest = f"{remote_name}:{remote_path}"
    rc, stdout, stderr = _rclone("copy", local_path, dest, "--progress")
    if rc == 0:
        return True, stdout
    return False, stderr


def delete_old_backups(remote_name: str, remote_path: str, retention_days: int) -> None:
    dest = f"{remote_name}:{remote_path}"
    rc, stdout, stderr = _rclone("delete", dest, f"--min-age={retention_days}d")
    if rc != 0:
        logger.warning("delete_old_backups failed for %s: %s", dest, stderr)


def remove_remote(remote_name: str) -> None:
    if not os.path.exists(RCLONE_CONFIG_PATH):
        return

    with open(RCLONE_CONFIG_PATH, "r") as fh:
        lines = fh.readlines()

    result_lines: list[str] = []
    inside_target = False
    for line in lines:
        stripped = line.strip()
        if stripped == f"[{remote_name}]":
            inside_target = True
            continue
        if inside_target and stripped.startswith("[") and stripped.endswith("]"):
            inside_target = False
        if not inside_target:
            result_lines.append(line)

    with open(RCLONE_CONFIG_PATH, "w") as fh:
        fh.writelines(result_lines)
