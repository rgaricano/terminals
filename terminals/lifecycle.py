"""Background lifecycle manager — cleans up idle terminal instances."""

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from terminals.audit import log_audit
from terminals.backends.base import Backend
from terminals.config import settings
from terminals.db.session import async_session
from terminals.models.tenants import Tenant, TenantStatus


async def _cleanup_idle(backend: Backend) -> int:
    """Tear down instances idle longer than the configured timeout.

    Returns the number of instances cleaned up.
    """
    if settings.idle_timeout_seconds <= 0:
        return 0  # cleanup disabled

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.idle_timeout_seconds
    )
    cleaned = 0

    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(
                Tenant.status == TenantStatus.running,
                Tenant.last_accessed_at < cutoff,
            )
        )
        idle_tenants = result.scalars().all()

        for tenant in idle_tenants:
            logger.info(
                "Cleaning up idle tenant {} (last access: {})",
                tenant.user_id,
                tenant.last_accessed_at,
            )
            try:
                if tenant.instance_id:
                    await backend.teardown(tenant.instance_id)
                tenant.status = TenantStatus.stopped
                cleaned += 1

                await log_audit(
                    action="idle_cleanup",
                    severity="info",
                    user_id=tenant.user_id,
                    resource_type="tenant",
                    resource_id=tenant.instance_id,
                    detail={
                        "last_accessed_at": str(tenant.last_accessed_at),
                        "idle_timeout_seconds": settings.idle_timeout_seconds,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to tear down instance for {}", tenant.user_id
                )
                tenant.status = TenantStatus.error

        if cleaned:
            await session.commit()

    return cleaned





async def run_lifecycle_loop(backend: Backend) -> None:
    """Periodically sweep for idle instances until cancelled."""
    interval = settings.cleanup_interval_seconds
    logger.info(
        "Lifecycle manager started (idle_timeout={}s, interval={}s)",
        settings.idle_timeout_seconds,
        interval,
    )
    while True:
        try:
            cleaned = await _cleanup_idle(backend)
            if cleaned:
                logger.info("Cleanup sweep: tore down {} idle instance(s)", cleaned)
        except Exception:
            logger.exception("Error during cleanup sweep")

        await asyncio.sleep(interval)
