"""FastAPI application assembly."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from terminals.backends import create_backend
from terminals.db.session import close_db, init_db
from terminals.lifecycle import run_lifecycle_loop
from terminals.logging import setup_logging
from terminals.middleware import RequestIdMiddleware
from terminals.routers.proxy import close_proxy_client, router as proxy_router
from terminals.routers.tenants import router as tenants_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    setup_logging()
    await init_db()
    app.state.backend = create_backend()

    # Start background lifecycle manager.
    lifecycle_task = asyncio.create_task(
        run_lifecycle_loop(app.state.backend)
    )

    yield

    # Cancel lifecycle manager on shutdown.
    lifecycle_task.cancel()
    try:
        await lifecycle_task
    except asyncio.CancelledError:
        pass

    await close_proxy_client()
    await app.state.backend.close()
    await close_db()


app = FastAPI(
    title="Terminals",
    description="Multi-tenant terminal orchestrator for Open Terminal.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tenants_router, prefix="/api/v1")
app.include_router(proxy_router)


@app.get("/health")
async def health():
    return {"status": True}


# ---------------------------------------------------------------------------
# Serve the SvelteKit static frontend (must be last — catch-all mount)
# ---------------------------------------------------------------------------
_FRONTEND_DIR = Path(__file__).resolve().parent / "frontend" / "build"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
