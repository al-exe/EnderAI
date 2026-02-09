from fastapi import APIRouter

from app.api.routes import items, library, login, private, runs, tasks, users, utils, workflow_buckets
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(library.router)
api_router.include_router(workflow_buckets.router)
api_router.include_router(tasks.router)
api_router.include_router(runs.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
