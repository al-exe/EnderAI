from fastapi import APIRouter

from app.api.routes import (
    agent_credentials,
    billing,
    cases,
    context_packs,
    login,
    private,
    search,
    skills,
    topics,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(agent_credentials.router)
api_router.include_router(billing.router)
api_router.include_router(topics.router)
api_router.include_router(cases.router)
api_router.include_router(search.router)
api_router.include_router(context_packs.router)
api_router.include_router(skills.router)
api_router.include_router(utils.router)

if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
