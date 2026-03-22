import logging
import os
from typing import Any

import docker
from docker.errors import DockerException, NotFound

logger = logging.getLogger(__name__)


def _client() -> docker.DockerClient:
    return docker.from_env()


def list_containers() -> list[dict[str, Any]]:
    try:
        client = _client()
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            mounts = c.attrs.get("Mounts", [])
            vols = [
                {
                    "name": m.get("Name") or os.path.basename(m.get("Source", "")),
                    "source": m.get("Source", ""),
                    "destination": m.get("Destination", ""),
                    "type": m.get("Type", ""),
                }
                for m in mounts
                if m.get("Type") in ("volume", "bind") and m.get("Source")
            ]
            result.append({
                "id": c.short_id,
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                "volumes": vols,
            })
        return result
    except DockerException as exc:
        logger.error("list_containers failed: %s", exc)
        return []


def list_volumes() -> list[dict[str, Any]]:
    try:
        client = _client()
        vols = client.volumes.list()
        return [
            {
                "name": v.name,
                "mountpoint": v.attrs.get("Mountpoint", ""),
                "driver": v.attrs.get("Driver", ""),
            }
            for v in vols
        ]
    except DockerException as exc:
        logger.error("list_volumes failed: %s", exc)
        return []


def stop_container(name: str) -> bool:
    try:
        client = _client()
        container = client.containers.get(name)
        container.stop(timeout=30)
        return True
    except NotFound:
        logger.warning("stop_container: container %s not found", name)
        return False
    except DockerException as exc:
        logger.error("stop_container %s failed: %s", name, exc)
        return False


def start_container(name: str) -> bool:
    try:
        client = _client()
        container = client.containers.get(name)
        container.start()
        return True
    except NotFound:
        logger.warning("start_container: container %s not found", name)
        return False
    except DockerException as exc:
        logger.error("start_container %s failed: %s", name, exc)
        return False


def get_container_volumes(name: str) -> list[dict[str, Any]]:
    try:
        client = _client()
        container = client.containers.get(name)
        mounts = container.attrs.get("Mounts", [])
        result = []
        for m in mounts:
            result.append(
                {
                    "type": m.get("Type", ""),
                    "source": m.get("Source", ""),
                    "destination": m.get("Destination", ""),
                    "name": m.get("Name", ""),
                }
            )
        return result
    except DockerException as exc:
        logger.error("get_container_volumes %s failed: %s", name, exc)
        return []


def detect_compose_stacks() -> list[dict[str, Any]]:
    """
    Detect Docker Compose stacks by reading container labels.
    Groups containers by com.docker.compose.project label.
    Returns one entry per project with containers, volumes, and best-guess .env path.
    Works with stacks deployed via Portainer, docker compose, or docker-compose.
    """
    try:
        client = _client()
        containers = client.containers.list(all=True)

        projects: dict[str, dict] = {}
        for c in containers:
            labels = c.labels or {}
            project = labels.get("com.docker.compose.project", "")
            if not project:
                continue

            if project not in projects:
                working_dir = labels.get("com.docker.compose.project.working_dir", "")
                config_files = labels.get("com.docker.compose.project.config_files", "")
                projects[project] = {
                    "compose_project": project,
                    "working_dir": working_dir,
                    "config_files": config_files,
                    "containers": [],
                    "volumes": set(),
                    "env_file": os.path.join(working_dir, ".env") if working_dir else "",
                }

            projects[project]["containers"].append(c.name)

            for m in (c.attrs.get("Mounts") or []):
                if m.get("Type") == "volume" and m.get("Name"):
                    projects[project]["volumes"].add(m["Name"])

        result = []
        for data in projects.values():
            result.append({
                "compose_project": data["compose_project"],
                "working_dir": data["working_dir"],
                "env_file": data["env_file"],
                "containers": sorted(data["containers"]),
                "volumes": sorted(data["volumes"]),
            })

        return sorted(result, key=lambda x: x["compose_project"])

    except DockerException as exc:
        logger.error("detect_compose_stacks failed: %s", exc)
        return []


def run_db_restore(
    container_name: str,
    db_type: str,
    db_name: str,
    db_user: str,
    db_password: str,
    sql_path: str,
) -> bool:
    """Pipe a SQL dump file into the target container to restore the database."""
    try:
        if db_type == "mysql":
            cmd = [
                "docker", "exec", "-i", container_name,
                "mysql", f"-u{db_user}", f"-p{db_password}", db_name,
            ]
            env = None
        elif db_type == "postgres":
            cmd = [
                "docker", "exec", "-i",
                "-e", f"PGPASSWORD={db_password}",
                container_name,
                "psql", "-U", db_user, "-d", db_name,
            ]
            env = None
        else:
            logger.error("run_db_restore: unsupported db_type=%s", db_type)
            return False

        with open(sql_path, "rb") as sql_file:
            result = subprocess.run(
                cmd,
                stdin=sql_file,
                capture_output=True,
                timeout=600,
                env=env,
            )

        if result.returncode != 0:
            logger.error(
                "run_db_restore exited %d for %s/%s: %s",
                result.returncode, db_type, db_name,
                result.stderr.decode(errors="replace")[:500],
            )
            return False
        return True

    except Exception as exc:
        logger.error("run_db_restore failed: %s", exc)
        return False


def run_db_dump(
    container_name: str,
    db_type: str,
    db_name: str,
    db_user: str,
    db_password: str,
    output_path: str,
) -> bool:
    """Run a database dump inside the target container and write output to output_path."""
    try:
        client = _client()
        container = client.containers.get(container_name)

        if db_type == "mysql":
            cmd = f"mysqldump -u{db_user} -p{db_password} {db_name}"
            exec_result = container.exec_run(cmd, demux=False)
        elif db_type == "postgres":
            cmd = f"pg_dump -U {db_user} {db_name}"
            exec_result = container.exec_run(
                cmd,
                environment={"PGPASSWORD": db_password},
                demux=False,
            )
        else:
            logger.error("run_db_dump: unsupported db_type=%s", db_type)
            return False

        if exec_result.exit_code != 0:
            logger.error(
                "run_db_dump exited %d for %s/%s",
                exec_result.exit_code,
                db_type,
                db_name,
            )
            return False

        with open(output_path, "wb") as fh:
            fh.write(exec_result.output)
        return True

    except DockerException as exc:
        logger.error("run_db_dump failed: %s", exc)
        return False
