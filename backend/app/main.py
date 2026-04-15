from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.websocket import router as websocket_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(health_router)
app.include_router(websocket_router)
