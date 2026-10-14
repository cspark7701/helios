"""HELIOS Dashboard Router Package."""

from helios.dashboard.routers.llm import router as llm_router
from helios.dashboard.routers.plans import router as plans_router
from helios.dashboard.routers.status import router as status_router
from helios.dashboard.routers.tuning import router as tuning_router
from helios.dashboard.routers.ws import router as ws_router

__all__ = [
    "llm_router",
    "plans_router",
    "status_router",
    "tuning_router",
    "ws_router",
]
