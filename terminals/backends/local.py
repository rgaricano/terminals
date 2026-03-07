"""Local backend — spawns Open Terminal as a subprocess per user."""

import asyncio
import logging
import os
import secrets
import signal
from typing import Optional

from terminals.backends.base import Backend
from terminals.config import settings

log = logging.getLogger(__name__)


class LocalBackend(Backend):
    """Manage terminal instances as local subprocesses."""

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._next_port: int = settings.local_port_range_start

    def _allocate_port(self) -> int:
        port = self._next_port
        self._next_port += 1
        return port

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    async def provision(self, user_id: str) -> dict:
        api_key = secrets.token_urlsafe(24)
        port = self._allocate_port()
        instance_name = f"terminals-local-{user_id}"
        data_dir = os.path.join(settings.data_dir, user_id)
        os.makedirs(data_dir, exist_ok=True)

        env = os.environ.copy()
        env["OPEN_TERMINAL_API_KEY"] = api_key
        env["HOME"] = data_dir

        log.info(
            "Spawning local open-terminal for user %s on port %d",
            user_id,
            port,
        )

        process = await asyncio.create_subprocess_exec(
            settings.local_binary, "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--api-key", api_key,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        instance_id = str(process.pid)
        self._processes[instance_id] = process

        # Give the process a moment to start.
        await asyncio.sleep(0.5)

        return {
            "instance_id": instance_id,
            "instance_name": instance_name,
            "api_key": api_key,
            "host": "127.0.0.1",
            "port": port,
        }

    async def start(self, instance_id: str) -> bool:
        current = await self.status(instance_id)
        return current == "running"

    async def teardown(self, instance_id: str) -> None:
        process = self._processes.pop(instance_id, None)
        if process is None:
            return
        try:
            process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except ProcessLookupError:
            pass
        log.info("Terminated local process %s", instance_id)

    async def status(self, instance_id: str) -> str:
        process = self._processes.get(instance_id)
        if process is None:
            return "missing"
        if process.returncode is None:
            return "running"
        return "stopped"

    async def close(self) -> None:
        for instance_id in list(self._processes):
            await self.teardown(instance_id)
