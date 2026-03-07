"""Abstract base class for terminal backends."""

from abc import ABC, abstractmethod


class Backend(ABC):
    """Lifecycle interface for provisioning and managing terminal instances."""

    @abstractmethod
    async def provision(self, user_id: str) -> dict:
        """Create a new terminal instance for *user_id*.

        Returns a dict with at least:
        ``instance_id``, ``instance_name``, ``api_key``, ``host``, ``port``.
        """

    @abstractmethod
    async def start(self, instance_id: str) -> bool:
        """Idempotent start — no-op if already running.

        Returns ``True`` if the instance is now running.
        """

    @abstractmethod
    async def teardown(self, instance_id: str) -> None:
        """Stop and remove the instance."""

    @abstractmethod
    async def status(self, instance_id: str) -> str:
        """Return ``'running'``, ``'stopped'``, or ``'missing'``."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources on shutdown."""
