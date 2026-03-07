"""Docker backend — provisions Open Terminal inside containers via aiodocker."""

import logging
import secrets
from typing import Optional

import aiodocker

from terminals.backends.base import Backend
from terminals.config import settings

log = logging.getLogger(__name__)


class DockerBackend(Backend):
    """Manage terminal instances as Docker containers."""

    def __init__(self) -> None:
        self._docker: Optional[aiodocker.Docker] = None

    async def _get_docker(self) -> aiodocker.Docker:
        if self._docker is None:
            self._docker = aiodocker.Docker()
        return self._docker

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    async def provision(self, user_id: str) -> dict:
        docker = await self._get_docker()
        api_key = secrets.token_urlsafe(24)
        instance_name = f"terminals-{user_id}"
        host_data_dir = f"{settings.data_dir}/{user_id}"

        config: dict = {
            "Image": settings.image,
            "Env": [f"OPEN_TERMINAL_API_KEY={api_key}"],
            "HostConfig": {
                "Binds": [f"{host_data_dir}:/home/user"],
            },
            "ExposedPorts": {"8000/tcp": {}},
        }

        if settings.network:
            config["HostConfig"]["NetworkMode"] = settings.network

        log.info("Provisioning container %s for user %s", instance_name, user_id)

        try:
            container = await docker.containers.create_or_replace(
                name=instance_name,
                config=config,
            )
            await container.start()
        except aiodocker.exceptions.DockerError as exc:
            log.error("Failed to provision container for %s: %s", user_id, exc)
            raise

        info = await container.show()
        instance_id = info["Id"]

        # Determine the hostname the orchestrator can reach.
        host = instance_name  # works when on the same Docker network
        if not settings.network:
            networks = info.get("NetworkSettings", {}).get("Networks", {})
            bridge = networks.get("bridge", {})
            host = bridge.get("IPAddress", "127.0.0.1")

        return {
            "instance_id": instance_id,
            "instance_name": instance_name,
            "api_key": api_key,
            "host": host,
            "port": 8000,
        }

    async def start(self, instance_id: str) -> bool:
        current = await self.status(instance_id)
        if current == "running":
            return True
        if current == "stopped":
            docker = await self._get_docker()
            try:
                container = await docker.containers.get(instance_id)
                await container.start()
                return True
            except aiodocker.exceptions.DockerError as exc:
                log.error("Failed to restart container %s: %s", instance_id, exc)
                return False
        return False  # missing

    async def teardown(self, instance_id: str) -> None:
        docker = await self._get_docker()
        try:
            container = await docker.containers.get(instance_id)
            await container.stop(t=10)
        except aiodocker.exceptions.DockerError:
            pass
        try:
            container = await docker.containers.get(instance_id)
            await container.delete(force=True)
        except aiodocker.exceptions.DockerError:
            log.warning("Could not remove container %s (may already be gone)", instance_id)

    async def status(self, instance_id: str) -> str:
        docker = await self._get_docker()
        try:
            container = await docker.containers.get(instance_id)
            info = await container.show()
            state = info.get("State", {})
            if state.get("Running"):
                return "running"
            return "stopped"
        except aiodocker.exceptions.DockerError:
            return "missing"

    async def close(self) -> None:
        if self._docker is not None:
            await self._docker.close()
            self._docker = None
