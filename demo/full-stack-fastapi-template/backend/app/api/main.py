from fastapi import APIRouter

from app.api.routes import (
    agent_credentials,
    billing,
    cases,
    context_packs,
    login,
    organizations,
    private,
    search,
    skills,
    taskforce,
    topics,
    users,
    utils,
    v2_byok,
    v2_documents,
    v2_metrics,
    v2_search,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(organizations.router)
api_router.include_router(agent_credentials.router)
api_router.include_router(billing.router)
api_router.include_router(topics.router)
api_router.include_router(cases.router)
api_router.include_router(search.router)
api_router.include_router(context_packs.router)
api_router.include_router(skills.router)
api_router.include_router(v2_documents.router)
api_router.include_router(v2_metrics.router)
api_router.include_router(taskforce.router)
api_router.include_router(v2_byok.router)
api_router.include_router(v2_search.router)
api_router.include_router(utils.router)

if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
