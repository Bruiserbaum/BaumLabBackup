import logging
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
        return [
            {
                "id": c.short_id,
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
            }
            for c in containers
        ]
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
