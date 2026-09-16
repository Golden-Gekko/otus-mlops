import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import mlflow
from pyspark.ml import PipelineModel
from pyspark.ml.functions import vector_to_array
from pyspark.sql import SparkSession
from pyspark.sql.functions import col

from app.config import settings
from app.features import INPUT_SCHEMA, prepare_features
from app.lag import cpu_lag
from app.schemas import PredictionOutput, TransactionInput

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self) -> None:
        self._spark: SparkSession | None = None
        self._model: PipelineModel | None = None
        self._ready: bool = False

    def _create_spark_session(self) -> SparkSession:
        logger.info('Создание SparkSession в local mode')
        return (
            SparkSession.builder.appName('fraud-api')
            .master('local[*]')
            .config('spark.sql.adaptive.enabled', 'false')
            .config('spark.hadoop.fs.s3a.impl', 'org.apache.hadoop.fs.s3a.S3AFileSystem')
            .getOrCreate()
        )

    def _resolve_tracking_uri(self) -> str:
        uri = settings.mlflow_tracking_uri
        if uri.startswith('file:'):
            path = Path(uri[len('file:'):])
            if not path.is_absolute():
                path = Path.cwd() / path
            return path.resolve().as_uri()
        return uri

    def _resolve_model_uri(self) -> str:
        return f'models:/{settings.mlflow_model_name}@{settings.mlflow_model_alias}'

    def load_model(self) -> None:
        if self._ready:
            return

        tracking_uri = self._resolve_tracking_uri()
        mlflow.set_tracking_uri(tracking_uri)

        model_uri = self._resolve_model_uri()
        logger.info('Загрузка модели из MLflow (%s): %s', tracking_uri, model_uri)

        local_dir = mlflow.artifacts.download_artifacts(artifact_uri=model_uri)
        logger.info('Артефакт модели скачан: %s', local_dir)

        self._spark = self._create_spark_session()
        self._model = mlflow.spark.load_model(local_dir)
        self._ready = True
        logger.info('Модель успешно загружена')

    @property
    def ready(self) -> bool:
        return self._ready

    @contextmanager
    def _session_scope(self):
        if self._spark is None:
            self.load_model()
        try:
            yield self._spark
        finally:
            pass

    def predict(self, transactions: list[TransactionInput]) -> list[PredictionOutput]:
        if not self._ready:
            self.load_model()

        rows = [t.model_dump() for t in transactions]
        df = self._spark.createDataFrame(rows, schema=INPUT_SCHEMA)
        featured = prepare_features(df)

        preds = self._model.transform(featured)
        out = (
            preds.withColumn('probability_arr', vector_to_array(col('probability')))
            .select(
                col('transaction_id').cast('long').alias('transaction_id'),
                col('prediction').cast('int').alias('prediction'),
                col('probability_arr')[1].alias('probability'),
            )
            .collect()
        )

        # Искусственная задержка для имитации тяжёлой модели.
        cpu_lag(settings.cpu_lag_ticks)

        return [
            PredictionOutput(
                transaction_id=row.transaction_id,
                prediction=row.prediction,
                probability=round(float(row.probability), 6),
            )
            for row in out
        ]

    def health(self) -> dict[str, Any]:
        return {
            'status': 'healthy',
            'model_loaded': self._ready,
            'model_name': settings.mlflow_model_name,
            'model_alias': settings.mlflow_model_alias,
        }
