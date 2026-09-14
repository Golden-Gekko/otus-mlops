import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.model import ModelManager
from app.schemas import PredictionRequest, PredictionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def get_model_manager(request: Request) -> ModelManager:
    return request.app.state.model_manager


@router.get('/health')
async def health(request: Request) -> dict[str, Any]:
    return get_model_manager(request).health()


@router.get('/ready')
async def ready(request: Request) -> dict[str, Any]:
    try:
        get_model_manager(request).load_model()
        return {'status': 'ready'}
    except Exception as exc:
        logger.exception('Модель не готова')
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'Модель не загружена: {exc}',
        )


@router.post('/predict', response_model=PredictionResponse)
async def predict(predict_data: PredictionRequest, request: Request) -> PredictionResponse:
    if not predict_data.transactions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Список транзакций пуст',
        )

    try:
        predictions = get_model_manager(request).predict(predict_data.transactions)
        return PredictionResponse(predictions=predictions)
    except Exception as exc:
        logger.exception('Ошибка инференса')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Ошибка инференса: {exc}',
        )
