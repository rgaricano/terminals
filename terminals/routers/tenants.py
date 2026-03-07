"""Tenant CRUD API routes."""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from terminals.audit import log_audit
from terminals.config import settings
from terminals.db.session import async_session
from terminals.models.tenants import Tenant, TenantStatus
from terminals.models.audit import AuditLog
from terminals.models.schemas import AuditLogResponse, TenantResponse

import httpx

router = APIRouter()

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

_owui_client: Optional[httpx.AsyncClient] = None


async def _get_owui_client() -> httpx.AsyncClient:
    global _owui_client
    if _owui_client is None:
        _owui_client = httpx.AsyncClient(timeout=10.0)
    return _owui_client


async def validate_token(token: str) -> Optional[str]:
    """Validate a bearer token against the Open WebUI instance.

    Returns the verified user ID on success.
    Raises ``HTTPException`` on failure.

    Only call when ``settings.open_webui_url`` is set.
    """
    client = await _get_owui_client()
    url = settings.open_webui_url.rstrip("/")
    try:
        resp = await client.get(
            f"{url}/api/v1/auths/",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Failed to reach Open WebUI")

    data = resp.json()
    verified_user_id = data.get("id")
    if not verified_user_id:
        raise HTTPException(status_code=401, detail="Token response missing user ID")
    return verified_user_id


async def verify_api_key(
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """Validate the caller's token.

    Supports three modes:
      1. Open WebUI - validates the JWT against the configured Open WebUI instance
      2. API Key    - checks against TERMINALS_API_KEY
      3. Open       - no auth when neither is configured

    Returns the verified user ID when using Open WebUI JWT validation,
    or ``None`` for API-key / open modes (where ``X-User-Id`` is trusted).
    """
    # Mode 1: Open WebUI JWT validation
    if settings.open_webui_url:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        return await validate_token(token)

    # Mode 2: Static API key
    if settings.api_key:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or token != settings.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return None

    # Mode 3: Open access (no key configured)
    return None


async def verify_user_id(
    verified_id: Optional[str] = Depends(verify_api_key),
    x_user_id: str = Header(..., alias="X-User-Id"),
) -> str:
    """Return the effective user ID after verifying against JWT identity.

    In JWT mode (``open_webui_url`` configured), the user ID extracted from
    the validated token **must** match ``X-User-Id``.  In API-key or open
    modes the header is trusted as-is.
    """
    if verified_id is not None and verified_id != x_user_id:
        raise HTTPException(
            status_code=403,
            detail="X-User-Id does not match authenticated identity",
        )
    return x_user_id


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _get_tenant(session: AsyncSession, user_id: str) -> Optional[Tenant]:
    result = await session.execute(select(Tenant).where(Tenant.user_id == user_id))
    return result.scalar_one_or_none()


async def _provision_tenant(request: Request, session: AsyncSession, user_id: str) -> Tenant:
    """Provision a new instance via the active backend and persist the tenant row."""
    backend = request.app.state.backend
    info = await backend.provision(user_id)
    tenant = Tenant(
        user_id=user_id,
        instance_id=info["instance_id"],
        instance_name=info["instance_name"],
        backend_type=settings.backend,
        api_key=info["api_key"],
        host=info["host"],
        port=info["port"],
        status=TenantStatus.running,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")


def _request_id(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


@router.post("/tenants/", response_model=TenantResponse)
async def create_tenant(
    request: Request,
    background_tasks: BackgroundTasks,
    x_user_id: str = Depends(verify_user_id),
):
    """Provision a terminal for a user (idempotent)."""
    backend = request.app.state.backend
    async with async_session() as session:
        tenant = await _get_tenant(session, x_user_id)
        if tenant is not None:
            # Ensure existing instance is running.
            if tenant.instance_id:
                running = await backend.start(tenant.instance_id)
                if running and tenant.status != TenantStatus.running:
                    old_status = tenant.status.value
                    tenant.status = TenantStatus.running
                    await session.commit()
                    await session.refresh(tenant)
                    background_tasks.add_task(
                        log_audit,
                        action="tenant_started",
                        severity="info",
                        user_id=x_user_id,
                        request_id=_request_id(request),
                        resource_type="tenant",
                        resource_id=tenant.instance_id,
                        detail={"before": old_status, "after": "running"},
                        ip_address=_client_ip(request),
                        user_agent=_user_agent(request),
                        status_code=200,
                    )
            return tenant

        tenant = await _provision_tenant(request, session, x_user_id)
        background_tasks.add_task(
            log_audit,
            action="tenant_created",
            severity="info",
            user_id=x_user_id,
            request_id=_request_id(request),
            resource_type="tenant",
            resource_id=tenant.instance_id,
            detail={
                "instance_name": tenant.instance_name,
                "backend": tenant.backend_type,
                "host": tenant.host,
                "port": tenant.port,
            },
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            status_code=200,
        )
        return tenant


@router.get("/tenants/", response_model=list[TenantResponse], dependencies=[Depends(verify_api_key)])
async def list_tenants():
    """List all tenants."""
    async with async_session() as session:
        result = await session.execute(select(Tenant))
        return result.scalars().all()


@router.get("/tenants/{user_id}", response_model=TenantResponse, dependencies=[Depends(verify_api_key)])
async def get_tenant(user_id: str):
    """Get a single tenant by user ID."""
    async with async_session() as session:
        tenant = await _get_tenant(session, user_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return tenant


@router.delete("/tenants/{user_id}", dependencies=[Depends(verify_api_key)])
async def delete_tenant(request: Request, background_tasks: BackgroundTasks, user_id: str):
    """Stop, remove the instance, and delete the tenant record."""
    backend = request.app.state.backend
    async with async_session() as session:
        tenant = await _get_tenant(session, user_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")

        instance_id = tenant.instance_id
        if instance_id:
            await backend.teardown(instance_id)

        await session.delete(tenant)
        await session.commit()

        background_tasks.add_task(
            log_audit,
            action="tenant_deleted",
            severity="warning",
            user_id=user_id,
            request_id=_request_id(request),
            resource_type="tenant",
            resource_id=instance_id,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            status_code=200,
        )
        return {"detail": "deleted"}


@router.post("/tenants/{user_id}/start", response_model=TenantResponse, dependencies=[Depends(verify_api_key)])
async def start_tenant(request: Request, background_tasks: BackgroundTasks, user_id: str):
    """Start a stopped tenant instance."""
    backend = request.app.state.backend
    async with async_session() as session:
        tenant = await _get_tenant(session, user_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        if not tenant.instance_id:
            raise HTTPException(status_code=400, detail="No instance to start")

        running = await backend.start(tenant.instance_id)
        if running:
            old_status = tenant.status.value
            tenant.status = TenantStatus.running
            await session.commit()
            await session.refresh(tenant)
            background_tasks.add_task(
                log_audit, action="tenant_started", severity="info",
                user_id=user_id, request_id=_request_id(request),
                resource_type="tenant", resource_id=tenant.instance_id,
                detail={"before": old_status, "after": "running"},
                ip_address=_client_ip(request),
            )
        return tenant


@router.post("/tenants/{user_id}/stop", response_model=TenantResponse, dependencies=[Depends(verify_api_key)])
async def stop_tenant(request: Request, background_tasks: BackgroundTasks, user_id: str):
    """Stop a tenant instance (keeps DB record)."""
    backend = request.app.state.backend
    async with async_session() as session:
        tenant = await _get_tenant(session, user_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        if not tenant.instance_id:
            raise HTTPException(status_code=400, detail="No instance to stop")

        await backend.teardown(tenant.instance_id)
        old_status = tenant.status.value
        tenant.status = TenantStatus.stopped
        await session.commit()
        await session.refresh(tenant)
        background_tasks.add_task(
            log_audit, action="tenant_stopped", severity="info",
            user_id=user_id, request_id=_request_id(request),
            resource_type="tenant", resource_id=tenant.instance_id,
            detail={"before": old_status, "after": "stopped"},
            ip_address=_client_ip(request),
        )
        return tenant


@router.get("/config", dependencies=[Depends(verify_api_key)])
async def get_config():
    """Return sanitized runtime configuration (no secrets)."""
    return {
        "backend": settings.backend,
        "image": settings.image,
        "network": settings.network,
        "data_dir": settings.data_dir,
        "port": settings.port,
        "host": settings.host,
        "idle_timeout_seconds": settings.idle_timeout_seconds,
        "cleanup_interval_seconds": settings.cleanup_interval_seconds,
        "kubernetes_namespace": settings.kubernetes_namespace,
        "kubernetes_image": settings.kubernetes_image,
        "kubernetes_storage_class": settings.kubernetes_storage_class,
        "kubernetes_storage_size": settings.kubernetes_storage_size,
        "kubernetes_service_type": settings.kubernetes_service_type,
        "has_api_key": bool(settings.api_key),
        "has_open_webui_url": bool(settings.open_webui_url),
        "has_siem_webhook": bool(settings.siem_webhook_url),
    }


@router.get("/stats", dependencies=[Depends(verify_api_key)])
async def get_stats():
    """Return aggregate stats for the dashboard."""
    from terminals.routers.proxy import active_ws_connections

    async with async_session() as session:
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()

    total = len(tenants)
    running = sum(1 for t in tenants if t.status == TenantStatus.running)
    stopped = sum(1 for t in tenants if t.status == TenantStatus.stopped)
    error = sum(1 for t in tenants if t.status == TenantStatus.error)

    return {
        "total": total,
        "running": running,
        "stopped": stopped,
        "error": error,
        "active_ws_connections": active_ws_connections,
    }


@router.get("/audit-logs", response_model=list[AuditLogResponse], dependencies=[Depends(verify_api_key)])
async def list_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None),
    user_id: str | None = Query(None),
):
    """Query persistent audit logs with optional filters."""
    async with async_session() as session:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

