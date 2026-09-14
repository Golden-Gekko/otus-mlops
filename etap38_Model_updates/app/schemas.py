from typing import Annotated

from pydantic import BaseModel, Field


class TransactionInput(BaseModel):
    transaction_id: Annotated[int, Field(description='ID транзакции')]
    tx_datetime: Annotated[str, Field(description='Дата и время транзакции, формат yyyy-MM-dd HH:mm:ss')]
    customer_id: Annotated[int, Field(description='ID клиента')]
    terminal_id: Annotated[int, Field(description='ID терминала')]
    tx_amount: Annotated[float, Field(description='Сумма транзакции')]
    tx_time_seconds: Annotated[int, Field(description='Время в секундах')]
    tx_time_days: Annotated[int, Field(description='Время в днях')]


class PredictionOutput(BaseModel):
    transaction_id: Annotated[int, Field(description='ID транзакции')]
    prediction: Annotated[int, Field(description='Предсказанный класс (0 — легитимная, 1 — мошенническая)')]
    probability: Annotated[float, Field(description='Вероятность мошенничества')]


class PredictionRequest(BaseModel):
    transactions: Annotated[list[TransactionInput], Field(description='Список транзакций для предсказания')]


class PredictionResponse(BaseModel):
    predictions: Annotated[list[PredictionOutput], Field(description='Список предсказаний')]
