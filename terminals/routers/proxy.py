"""Catch-all reverse proxy into tenant instances.

Routing is based on the ``X-User-Id`` header — the caller (e.g. Open WebUI
backend) sets this header and the proxy resolves / provisions the correct
instance automatically.  The path structure mirrors open-terminal exactly
(``/execute``, ``/files/list``, …) so the two are interchangeable.
"""

import asyncio
import json
import time
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response, WebSocket
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import func

from terminals.audit import log_audit
from terminals.config import settings
from terminals.db.session import async_session
from terminals.models.tenants import Tenant, TenantStatus
from terminals.routers.tenants import _get_tenant, _provision_tenant, validate_token, verify_api_key, verify_user_id

router = APIRouter()

# ---------------------------------------------------------------------------
# Proxy client
# ---------------------------------------------------------------------------

_proxy_client: Optional[httpx.AsyncClient] = None

# Active WebSocket connection counter (for stats endpoint)
active_ws_connections: int = 0


async def _get_proxy_client() -> httpx.AsyncClient:
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
    return _proxy_client


async def close_proxy_client() -> None:
    global _proxy_client
    if _proxy_client is not None:
        await _proxy_client.aclose()
        _proxy_client = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_ip(request) -> str:
    """Extract client IP, respecting X-Forwarded-For."""
    headers = getattr(request, "headers", {})
    forwarded = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    return client.host if client else ""


def _user_agent(request) -> str:
    headers = getattr(request, "headers", {})
    return headers.get("user-agent", "") if hasattr(headers, "get") else ""


def _request_id(request) -> Optional[str]:
    return getattr(getattr(request, "state", None), "request_id", None)


# ---------------------------------------------------------------------------
# Resolve tenant
# ---------------------------------------------------------------------------


async def _resolve_tenant(request, user_id: str) -> Tenant:
    """Return a running tenant, auto-provisioning if needed."""
    backend = request.app.state.backend
    async with async_session() as session:
        tenant = await _get_tenant(session, user_id)

        if tenant is None:
            tenant = await _provision_tenant(request, session, user_id)
            return tenant

        # Ensure the instance is alive.
        if tenant.instance_id:
            running = await backend.start(tenant.instance_id)
            if not running:
                # Re-provision.
                old_instance_id = tenant.instance_id
                await backend.teardown(tenant.instance_id)
                info = await backend.provision(user_id)
                tenant.instance_id = info["instance_id"]
                tenant.instance_name = info["instance_name"]
                tenant.api_key = info["api_key"]
                tenant.host = info["host"]
                tenant.port = info["port"]
                tenant.status = TenantStatus.running

                # Audit re-provision (fire-and-forget since we're not in a route).
                try:
                    await log_audit(
                        action="tenant_reprovisioned",
                        severity="warning",
                        user_id=user_id,
                        request_id=_request_id(request),
                        resource_type="tenant",
                        resource_id=tenant.instance_id,
                        detail={
                            "old_instance_id": old_instance_id,
                            "new_instance_id": info["instance_id"],
                        },
                        ip_address=_client_ip(request),
                    )
                except Exception:
                    logger.warning("Failed to audit tenant re-provision")

        # Touch the access timestamp for idle tracking.
        tenant.last_accessed_at = func.now()
        await session.commit()
        await session.refresh(tenant)

        return tenant


# ---------------------------------------------------------------------------
# Internal proxy helper
# ---------------------------------------------------------------------------


async def _proxy_request(
    request: Request, user_id: str, path: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Response:
    """Proxy a request to the user's Open Terminal instance."""
    tenant = await _resolve_tenant(request, user_id)

    target_url = f"http://{tenant.host}:{tenant.port}/{path}"
    if request.query_params:
        target_url += f"?{request.query_params}"

    headers = dict(request.headers)
    # Replace auth with the instance's own API key.
    headers["authorization"] = f"Bearer {tenant.api_key}"
    # Remove hop-by-hop / routing headers.
    for h in ("host", "transfer-encoding", "connection", "x-user-id"):
        headers.pop(h, None)

    body = await request.body()

    client = await _get_proxy_client()
    upstream = await client.request(
        method=request.method,
        url=target_url,
        headers=headers,
        content=body,
    )

    # Strip hop-by-hop from response too.
    response_headers = dict(upstream.headers)
    for h in ("transfer-encoding", "connection", "content-encoding", "content-length"):
        response_headers.pop(h, None)

    # Audit the proxied request.
    severity = "warning" if upstream.status_code >= 500 else "info"
    if background_tasks:
        background_tasks.add_task(
            log_audit,
            action="proxy_request",
            severity=severity,
            user_id=user_id,
            request_id=_request_id(request),
            resource_type="proxy",
            resource_id=tenant.instance_id,
            detail={"method": request.method, "path": path},
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            status_code=upstream.status_code,
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


# ---------------------------------------------------------------------------
# OpenAPI spec passthrough (tool discovery — no X-User-Id required)
# ---------------------------------------------------------------------------

_SPEC_CACHE_TTL = 300  # seconds
_cached_spec: Optional[dict] = None
_cached_spec_ts: float = 0.0

_SYSTEM_USER_ID = "__system__"


@router.get(
    "/terminals/openapi.json",
    dependencies=[Depends(verify_api_key)],
)
async def get_openapi_spec(request: Request):
    """Return the open-terminal OpenAPI spec.

    The spec is fetched from a running instance and cached for 5 minutes.
    This endpoint does **not** require ``X-User-Id`` — it is used by
    Open WebUI for tool discovery before any user context exists.
    """
    global _cached_spec, _cached_spec_ts

    now = time.monotonic()
    if _cached_spec is not None and (now - _cached_spec_ts) < _SPEC_CACHE_TTL:
        return JSONResponse(content=_cached_spec)

    # Find any running tenant to fetch the spec from, or provision a system one.
    tenant = await _resolve_tenant(request, _SYSTEM_USER_ID)

    client = await _get_proxy_client()
    try:
        resp = await client.get(
            f"http://{tenant.host}:{tenant.port}/openapi.json",
            headers={"Authorization": f"Bearer {tenant.api_key}"},
        )
        resp.raise_for_status()
        spec = resp.json()
    except Exception as e:
        logger.error("Failed to fetch OpenAPI spec from instance: {}", e)
        return JSONResponse(
            content={"error": "Failed to fetch OpenAPI spec from terminal instance"},
            status_code=502,
        )

    _cached_spec = spec
    _cached_spec_ts = now

    return JSONResponse(content=spec)


# ---------------------------------------------------------------------------
# Header-based catch-all proxy (primary integration point)
# ---------------------------------------------------------------------------


@router.api_route(
    "/terminals/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy(
    path: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_user_id: str = Depends(verify_user_id),
):
    """Reverse-proxy any request into the user's Open Terminal instance.

    The target user is identified by the ``X-User-Id`` header.  The path
    structure mirrors the open-terminal API exactly so the two backends
    are fully interchangeable from the caller's perspective.
    """
    return await _proxy_request(request, x_user_id, path, background_tasks)


# ---------------------------------------------------------------------------
# WebSocket proxy for interactive terminal sessions
# ---------------------------------------------------------------------------


@router.websocket("/terminals/api/terminals/{session_id}")
async def ws_terminal_proxy(
    ws: WebSocket,
    session_id: str,
    token: str = Query(""),
    user_id: str = Query(""),
):
    """Proxy a WebSocket terminal session to the user's Open Terminal instance.

    Authentication is via the ``token`` query parameter (validated against
    the orchestrator API key).  The ``user_id`` query param identifies the
    target tenant (equivalent to the ``X-User-Id`` header used by HTTP routes).
    """
    # Validate token — support JWT (Open WebUI) and API key modes.
    verified_user_id = None
    if settings.open_webui_url:
        # JWT mode — validate against Open WebUI and extract verified identity.
        try:
            verified_user_id = await validate_token(token)
        except Exception:
            await ws.close(code=4001, reason="Invalid token")
            await log_audit(
                action="auth_failed",
                severity="critical",
                user_id=user_id or None,
                resource_type="websocket",
                detail={"reason": "JWT validation failed", "session_id": session_id},
                ip_address=_client_ip(ws),
            )
            return
    elif settings.api_key and token != settings.api_key:
        await ws.close(code=4001, reason="Invalid API key")
        await log_audit(
            action="auth_failed",
            severity="critical",
            user_id=user_id or None,
            resource_type="websocket",
            detail={"reason": "Invalid API key", "session_id": session_id},
            ip_address=_client_ip(ws),
        )
        return

    if not user_id:
        await ws.close(code=4002, reason="Missing user_id")
        return

    # In JWT mode, enforce that user_id matches the verified identity.
    if verified_user_id is not None and verified_user_id != user_id:
        await ws.close(code=4003, reason="user_id does not match authenticated identity")
        await log_audit(
            action="auth_failed",
            severity="critical",
            user_id=user_id,
            resource_type="websocket",
            detail={
                "reason": "user_id mismatch",
                "claimed": user_id,
                "verified": verified_user_id,
                "session_id": session_id,
            },
            ip_address=_client_ip(ws),
        )
        return

    await ws.accept()

    global active_ws_connections
    active_ws_connections += 1

    # Audit WS connect.
    await log_audit(
        action="ws_connect",
        severity="info",
        user_id=user_id,
        resource_type="websocket",
        resource_id=session_id,
        ip_address=_client_ip(ws),
        user_agent=_user_agent(ws),
    )

    try:
        tenant = await _resolve_tenant(ws, user_id)
    except Exception as e:
        logger.error("Failed to resolve tenant for WS: {}", e)
        await ws.close(code=4003, reason="Failed to resolve terminal instance")
        return

    upstream_url = f"ws://{tenant.host}:{tenant.port}/api/terminals/{session_id}"

    import websockets

    try:
        async with websockets.connect(upstream_url) as upstream:
            # First-message auth to upstream
            await upstream.send(json.dumps({"type": "auth", "token": tenant.api_key}))

            async def _client_to_upstream():
                """Forward client WebSocket → upstream."""
                try:
                    while True:
                        msg = await ws.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        elif "bytes" in msg and msg["bytes"]:
                            await upstream.send(msg["bytes"])
                        elif "text" in msg and msg["text"]:
                            await upstream.send(msg["text"])
                except Exception:
                    pass

            async def _upstream_to_client():
                """Forward upstream → client WebSocket."""
                try:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await ws.send_bytes(message)
                        else:
                            await ws.send_text(message)
                except Exception:
                    pass

            await asyncio.gather(
                _client_to_upstream(),
                _upstream_to_client(),
                return_exceptions=True,
            )
    except Exception as e:
        logger.error("WebSocket terminal proxy error: {}", e)
    finally:
        active_ws_connections -= 1
        # Audit WS disconnect.
        try:
            await log_audit(
                action="ws_disconnect",
                severity="info",
                user_id=user_id,
                resource_type="websocket",
                resource_id=session_id,
                ip_address=_client_ip(ws),
            )
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass
