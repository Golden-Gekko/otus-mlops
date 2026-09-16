import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import settings
from app.model import ModelManager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Сервис %s запущен', settings.app_name)
    app.state.model_manager = ModelManager()
    yield
    logger.info('Сервис %s остановлен', settings.app_name)


app = FastAPI(
    title='Fraud Detection API',
    description='REST API для инференса модели детекции мошенничества',
    lifespan=lifespan,
)

app.include_router(router)
