import argparse
import logging
import random
import sys
from argparse import ArgumentParser
from datetime import datetime, timedelta
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient
from pyspark.ml import Pipeline
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StandardScaler, VectorAssembler
from pyspark.sql import SparkSession
from pyspark.sql.types import IntegerType, StructField, StructType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.features import (  # noqa: E402
    INPUT_SCHEMA,
    MODEL_FEATURE_COLS,
    prepare_features,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('train_stub')

TRAIN_SCHEMA = StructType(
    list(INPUT_SCHEMA.fields) + [StructField('target', IntegerType(), True)]
)


def resolve_tracking_uri(uri: str) -> str:
    if uri.startswith('file:'):
        path = Path(uri[len('file:'):])
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve().as_uri()
    return uri


def generate_rows(rows: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    base = datetime(2024, 1, 1)
    data = []
    for i in range(1, rows + 1):
        tx_time = base + timedelta(seconds=rng.randrange(365 * 86400))
        tx_time_seconds = int(tx_time.timestamp())
        is_fraud = rng.random() < 0.02
        if is_fraud:
            tx_amount = round(1500.0 + rng.expovariate(1 / 1000.0), 2)
        else:
            tx_amount = round(rng.lognormvariate(5, 1), 2)
        data.append(
            {
                'transaction_id': i,
                'tx_datetime': tx_time.strftime('%Y-%m-%d %H:%M:%S'),
                'customer_id': rng.randrange(1, 201),
                'terminal_id': rng.randrange(1, 51),
                'tx_amount': min(tx_amount, 10000.0),
                'tx_time_seconds': tx_time_seconds,
                'tx_time_days': tx_time_seconds // 86400,
                'target': int(is_fraud),
            }
        )
    return data


def build_pipeline(seed: int) -> Pipeline:
    stages = [
        VectorAssembler(
            inputCols=MODEL_FEATURE_COLS,
            outputCol='features_raw',
            handleInvalid='skip',
        ),
        StandardScaler(
            inputCol='features_raw',
            outputCol='features',
            withStd=True,
            withMean=True,
        ),
        RandomForestClassifier(
            labelCol='target',
            featuresCol='features',
            numTrees=5,
            maxDepth=4,
            seed=seed,
        ),
    ]
    return Pipeline(stages=stages)


def register_model(model_name: str, alias: str) -> str:
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    latest = max(versions, key=lambda v: int(v.version))
    client.set_registered_model_alias(model_name, alias, latest.version)
    return latest.version


def parse_args() -> argparse.Namespace:
    parser = ArgumentParser(description='Обучение stub-модели (автономный режим)')
    parser.add_argument('--rows', type=int, default=5000)
    parser.add_argument('--tracking-uri', default=settings.mlflow_tracking_uri)
    parser.add_argument('--output', default='models/stub')
    parser.add_argument('--model-name', default=settings.mlflow_model_name)
    parser.add_argument('--alias', default=settings.mlflow_model_alias)
    parser.add_argument('--seed', type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    spark = (
        SparkSession.builder.appName('train-stub')
        .master('local[*]')
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel('WARN')

    try:
        df = spark.createDataFrame(generate_rows(args.rows, args.seed), TRAIN_SCHEMA)
        df = prepare_features(df)
        train_df, test_df = df.randomSplit([0.8, 0.2], seed=args.seed)

        model = build_pipeline(args.seed).fit(train_df)

        predictions = model.transform(test_df)
        auc = BinaryClassificationEvaluator(
            labelCol='target',
            rawPredictionCol='rawPrediction',
            metricName='areaUnderROC',
        ).evaluate(predictions)
        logger.info('Test AUC: %.4f', auc)

        tracking_uri = resolve_tracking_uri(args.tracking_uri)
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment('fraud_stub')
        with mlflow.start_run(run_name='stub'):
            mlflow.log_param('rows', args.rows)
            mlflow.log_param('seed', args.seed)
            mlflow.log_param('model_name', args.model_name)
            mlflow.log_metric('test_auc', auc)
            mlflow.spark.log_model(
                model,
                artifact_path='model',
                registered_model_name=args.model_name,
            )

        version = register_model(args.model_name, args.alias)
        logger.info('Alias @%s -> версия %s', args.alias, version)

        model.write().overwrite().save(args.output)
        logger.info('Модель сохранена: %s', args.output)
        logger.info(
            'Готово: models:/%s@%s (tracking: %s)',
            args.model_name,
            args.alias,
            tracking_uri,
        )
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
