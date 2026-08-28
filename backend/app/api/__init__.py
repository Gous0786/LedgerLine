from fastapi import APIRouter

from app.api import chat, datasets, health, metrics, proposals, runs

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(datasets.router)
api_router.include_router(runs.router)
api_router.include_router(metrics.router)
api_router.include_router(proposals.router)
api_router.include_router(proposals.rules_router)
