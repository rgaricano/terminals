"""Centralised audit-logging helper.

Emits structured audit events via:
  1. Database — persistent ``audit_logs`` table
  2. Loguru  — structured log line (always)
  3. SIEM    — optional webhook forwarding
"""

import json
from typing import Optional

import httpx
from loguru import logger

from terminals.config import settings
from terminals.db.session import async_session

# Reusable SIEM webhook client (created once, not per-event).
_siem_client: Optional[httpx.AsyncClient] = None


async def _get_siem_client() -> httpx.AsyncClient:
    global _siem_client
    if _siem_client is None:
        _siem_client = httpx.AsyncClient(timeout=5.0)
    return _siem_client


async def log_audit(
    *,
    action: str,
    severity: str = "info",
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    detail: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    status_code: Optional[int] = None,
) -> None:
    """Emit a structured audit event via DB + loguru + optional SIEM webhook."""

    event = {
        "action": action,
        "severity": severity,
        "user_id": user_id,
        "request_id": request_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "detail": detail,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "status_code": status_code,
    }

    # ------ 1. Database persistence ------
    try:
        from terminals.models.audit import AuditLog

        async with async_session() as session:
            session.add(AuditLog(**event))
            await session.commit()
    except Exception:
        logger.warning("Failed to persist audit event to database")

    # ------ 2. Loguru structured emit ------
    level = {"info": "INFO", "warning": "WARNING", "critical": "ERROR"}.get(
        severity, "INFO"
    )
    logger.log(level, "AUDIT | {action} | user={user_id} | {detail}", **event)

    # ------ 3. SIEM webhook ------
    if settings.siem_webhook_url:
        try:
            client = await _get_siem_client()
            await client.post(
                settings.siem_webhook_url,
                json={k: v for k, v in event.items() if v is not None},
            )
        except Exception:
            logger.warning("Failed to forward audit event to SIEM webhook")
