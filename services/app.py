"""
PDS360 "single service" API gateway.

Render gives one public HTTP port per Web Service. This file combines all the
microservices into a single FastAPI app while keeping the same route paths
(`/auth/*`, `/api/*`) so the frontend doesn't need to change.

Run (local):
  cd services
  uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import Iterable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _iter_routes(sub_app: FastAPI):
    # Starlette routes; FastAPI adds docs/openapi routes by default which would
    # conflict when combining apps. We skip those and keep the gateway docs.
    for r in sub_app.router.routes:
        path = getattr(r, "path", None)
        if path in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}:
            continue
        # Avoid collisions: every microservice defines its own `/health`.
        if path == "/health":
            continue
        yield r


def _include_routes(gateway: FastAPI, sub_app: FastAPI) -> None:
    for r in _iter_routes(sub_app):
        gateway.router.routes.append(r)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Combine lifespan hooks from the individual microservices.

    Each service manages its own DB create/seed/startup steps. We execute them
    once here so the merged gateway behaves the same.
    """

    # Import inside lifespan so importing this module doesn't accidentally
    # execute heavy startup work.
    from auth_service import main as auth_main
    from overview import main as overview_main
    from smart_allot import main as smart_allot_main
    from anomalies import main as anomalies_main
    from pdsaibot import main as pdsaibot_main
    from call_centre import main as call_centre_main

    # Some services define lifespan, some don't. Enter them in a stable order.
    candidates = [
        getattr(auth_main, "lifespan", None),
        getattr(overview_main, "lifespan", None),
        getattr(smart_allot_main, "lifespan", None),
        getattr(anomalies_main, "lifespan", None),
        getattr(pdsaibot_main, "lifespan", None),
        getattr(call_centre_main, "lifespan", None),
    ]

    async with AsyncExitStack() as stack:
        for lf in candidates:
            if lf is None:
                continue
            # FastAPI lifespan is an async context manager factory.
            await stack.enter_async_context(lf(app))
        yield


app = FastAPI(
    title="PDS360 — Unified Service",
    version="3.0.0",
    lifespan=lifespan,
)

# One CORS policy at the gateway level.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _wire_routes() -> None:
    # Import service apps and merge their routes into this gateway.
    from auth_service import main as auth_main
    from overview import main as overview_main
    from smart_allot import main as smart_allot_main
    from anomalies import main as anomalies_main
    from pdsaibot import main as pdsaibot_main
    from call_centre import main as call_centre_main

    for sub in [
        auth_main.app,
        overview_main.app,
        smart_allot_main.app,
        anomalies_main.app,
        pdsaibot_main.app,
        call_centre_main.app,
    ]:
        _include_routes(app, sub)


_wire_routes()


@app.get("/health")
def health():
    return {"status": "ok", "service": "unified", "modules": 6}
