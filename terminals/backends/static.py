"""Static backend — proxies to a pre-running Open Terminal instance."""

import logging

import httpx

from terminals.backends.base import Backend
from terminals.config import settings

log = logging.getLogger(__name__)


class StaticBackend(Backend):
    """Point at an already-running Open Terminal instance.

    No lifecycle management — the admin is responsible for keeping the
    target instance alive.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=5.0)

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    async def provision(self, user_id: str) -> dict:
        return {
            "instance_id": "static",
            "instance_name": "static",
            "api_key": settings.static_api_key,
            "host": settings.static_host,
            "port": settings.static_port,
        }

    async def start(self, instance_id: str) -> bool:
        try:
            resp = await self._client.get(
                f"http://{settings.static_host}:{settings.static_port}/health"
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def teardown(self, instance_id: str) -> None:
        pass  # no-op — admin manages the instance

    async def status(self, instance_id: str) -> str:
        running = await self.start(instance_id)
        return "running" if running else "missing"

    async def close(self) -> None:
        await self._client.aclose()
