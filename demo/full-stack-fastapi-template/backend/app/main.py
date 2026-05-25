import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.search import indexing as search_indexing

log = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Search indexer: long-running asyncio task that polls v2_document
    # for drift and re-embeds. Disabled when OPENAI_API_KEY is unset
    # (the sweep itself no-ops, but we skip scheduling so logs stay
    # quiet during local dev without keys).
    sweeper_task: asyncio.Task[None] | None = None
    stop_event = asyncio.Event()
    if settings.OPENAI_API_KEY:
        sweeper_task = asyncio.create_task(
            search_indexing.run_forever(stop_event=stop_event),
            name="search-indexer",
        )
        log.info(
            "search indexer started (interval=%ss)",
            settings.SEARCH_INDEX_SWEEP_INTERVAL_SECONDS,
        )
    try:
        yield
    finally:
        stop_event.set()
        if sweeper_task is not None:
            sweeper_task.cancel()
            try:
                await sweeper_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
