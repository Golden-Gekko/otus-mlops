from argparse import ArgumentParser
from datetime import datetime, timezone
import os
import traceback
from typing import Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError
import mlflow
from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml.evaluation import (
    BinaryClassificationEvaluator, MulticlassClassificationEvaluator)
from pyspark.ml.feature import StandardScaler, StringIndexer, VectorAssembler
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import col, rand, dayofweek, month

LOG_FILE_PATH = '/tmp/data_train_job.log'
RANDOM_STATE = 42
TRAIN_SIZE = 0.8


def to_boto3_name(path: str):
    return path.replace('s3://', '').replace('s3a://', '').strip('/')


def log_message(msg: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{timestamp}] {msg}'
    with open(LOG_FILE_PATH, 'a') as f:
        f.write(line + '\n')


def init_s3_client(endpoint_url: str, access_key: str, secret_key: str):
    return boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def upload_log_to_s3(
        bucket: str, log_key: str, s3_cfg: Dict[str, str]):
    if not os.path.exists(LOG_FILE_PATH):
        return
    try:
        s3_client = init_s3_client(**s3_cfg)
        s3_client.upload_file(LOG_FILE_PATH, to_boto3_name(bucket), log_key)
        print(f'Лог успешно загружен в s3://{to_boto3_name(bucket)}/{log_key}')
    except ClientError as e:
        print(f'Ошибка загрузки лога в S3: {e}')
    except Exception as e:
        print(f'Неожиданная ошибка при загрузке лога: {e}')


def save_model_to_s3(model: PipelineModel, output_path: str):
    try:
        model.write().overwrite().save(output_path)
        log_message(f'Модель сохраненав S3: {output_path}')
    except Exception as e:
        log_message(f'ERROR: Ошибка сохранения модели: {str(e)}')
        raise


def create_spark_session(s3_cfg: Dict[str, str]) -> SparkSession:
    log_message('INFO: Инициализация Spark сессии')
    try:
        builder = (
            SparkSession.builder
            .appName('FraudDetectionModel')
        )

        builder = (
            builder.config(
                'spark.hadoop.fs.s3a.impl',
                'org.apache.hadoop.fs.s3a.S3AFileSystem')
            .config('spark.hadoop.fs.s3a.endpoint', s3_cfg['endpoint_url'])
            .config('spark.hadoop.fs.s3a.access.key', s3_cfg['access_key'])
            .config('spark.hadoop.fs.s3a.secret.key', s3_cfg['secret_key'])
            .config('spark.hadoop.fs.s3a.path.style.access', 'true')
            .config('spark.hadoop.fs.s3a.connection.ssl.enabled', 'true')
        )

        log_message('SUCCESS: Spark сессия успешно сконфигурирована')
        return builder.getOrCreate()
    except Exception as e:
        log_message(f'ERROR: Ошибка создания Spark сессии: {str(e)}')
        raise


def load_data(
    spark: SparkSession, input_path: str
) -> Tuple[DataFrame, List[str]]:
    log_message(f'INFO: Загрузка данных из {input_path}')

    df = spark.read.parquet(input_path)
    log_message(
        f'INFO: Загружено {df.count()} строк, {len(df.columns)} колонок')

    feature_cols = [
        'tx_datetime',
        'tx_fraud',
        'customer_id',
        'tx_amount',
        'tx_time_days',
        'terminal_id'
    ]

    missing_cols = [col for col in feature_cols if col not in df.columns]
    if missing_cols:
        log_message(f'ERROR: Отсутствуют колонки {missing_cols}')
        raise ValueError('Датасет не соответствует ожидаемому')
    # Таргет
    df = df.withColumn('target', col('tx_fraud').cast('int'))

    # Извлечение временных признаков
    df = df.withColumn('day_of_week', dayofweek(col('tx_datetime')))
    df = df.withColumn('month', month(col('tx_datetime')))

    # Логирование распределения классов
    if 'target' in df.columns:
        total_count = df.count()
        class_dist = df.groupBy('target').count().collect()
        log_message('INFO: Распределение классов в полном датасете:')
        for row in class_dist:
            log_message(
                f'INFO:   Class {row["target"]}: '
                f'{row["count"]} ({row["count"] / total_count:.2%}%)'
            )

    feature_cols = [
        'customer_id',
        'tx_amount',
        'tx_time_days',
        'terminal_id',
        'day_of_week',
        'month'
    ]

    log_message(f'INFO: Используемые признаки: {feature_cols}')

    return df, feature_cols


def prepare_features(df: DataFrame, feature_cols: List[str]):
    stages = []
    final_feature_cols = []

    for col_name in feature_cols:
        if df.schema[col_name].dataType.typeName() == 'string':
            indexer = StringIndexer(
                inputCol=col_name,
                outputCol=f'{col_name}_index',
                handleInvalid='skip'
            )
            stages.append(indexer)
            final_feature_cols.append(f'{col_name}_index')
        else:
            final_feature_cols.append(col_name)

    # Векторизация
    assembler = VectorAssembler(
        inputCols=final_feature_cols,
        outputCol='features_raw',
        handleInvalid='skip'
    )
    stages.append(assembler)

    # Масштабирование
    scaler = StandardScaler(
        inputCol='features_raw',
        outputCol='features',
        withStd=True,
        withMean=True
    )
    stages.append(scaler)

    return stages, final_feature_cols


def stratified_train_test_split(
    df: DataFrame,
    target: str = 'target',
    train_size: float = TRAIN_SIZE,
    seed: int = RANDOM_STATE
) -> Tuple[DataFrame, DataFrame]:
    # Сплит на каждый класс
    train_fraud, test_fraud = (
        df.filter(col(target) == 1)
        .randomSplit([train_size, 1 - train_size], seed=seed))
    train_legit, test_legit = (
        df.filter(col(target) == 0)
        .randomSplit([train_size, 1 - train_size], seed=seed))

    train_df = train_fraud.union(train_legit)
    test_df = test_fraud.union(test_legit)

    # Финальное перемешивание
    train_df = train_df.orderBy(rand(seed=seed + 1))
    test_df = test_df.orderBy(rand(seed=seed + 2))

    log_message('INFO: Разделение со стратификацией завершено.')

    return train_df, test_df


def train_model(
    train_df: DataFrame,
    test_df: DataFrame,
    feature_cols: List[str],
    tracking_uri: str,
    experiment_name: str,
    run_name: str,
):
    # Настройка MLflow
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    stages, feature_cols = prepare_features(train_df, feature_cols)

    try:
        # Начало эксперимента MLflow
        with mlflow.start_run(run_name=run_name) as run:
            run_id = run.info.run_id
            log_message(f'INFO: MLflow Run ID: {run_id}')

            mlflow.log_param('train_size', train_df.count())
            mlflow.log_param('test_size', test_df.count())
            mlflow.log_param('features', str(feature_cols))

            model = RandomForestClassifier(
                labelCol='target',
                featuresCol='features',
                numTrees=10,
                maxDepth=5,
                seed=RANDOM_STATE,
            )

            pipeline = Pipeline(stages=stages + [model])
            trained_pipeline = pipeline.fit(train_df)

            test_predictions = trained_pipeline.transform(test_df)

            evaluator_auc = BinaryClassificationEvaluator(
                labelCol='target',
                rawPredictionCol='rawPrediction',
                metricName='areaUnderROC'
            )
            evaluator_acc = MulticlassClassificationEvaluator(
                labelCol='target',
                predictionCol='prediction',
                metricName='accuracy'
            )
            evaluator_f1 = MulticlassClassificationEvaluator(
                labelCol='target',
                predictionCol='prediction',
                metricName='f1'
            )

            metrics = {}
            metrics['test_auc'] = evaluator_auc.evaluate(test_predictions)
            metrics['test_acc'] = evaluator_acc.evaluate(test_predictions)
            metrics['test_f1'] = evaluator_f1.evaluate(test_predictions)

            for name, value in metrics.items():
                log_message(f'INFO: {name}: {value:.4f}')
                mlflow.log_metric(name, value)

            # Сохранение модели в MLflow
            mlflow.spark.log_model(
                trained_pipeline,
                artifact_path='model',
                registered_model_name='fraud_detection_rf'
            )

            mlflow.set_tag('stage', 'champion')

            log_message('INFO: Модель успешно сохранена в MLflow')

            return trained_pipeline, test_predictions, metrics

    except Exception as e:
        log_message(f'ERROR: Ошибка обучения модели: {str(e)}')
        raise


def main():
    spark = None
    try:
        parser = ArgumentParser()

        parser.add_argument('--input_data', required=True)
        parser.add_argument('--output_model', required=True)

        parser.add_argument('--tracking_uri', required=True)
        parser.add_argument('--experiment_name', required=True)
        parser.add_argument('--run_name', required=True)

        parser.add_argument('--bucket', required=True)
        parser.add_argument('--s3_endpoint_url', required=True)
        parser.add_argument('--s3_access_key', required=True)
        parser.add_argument('--s3_secret_key', required=True)

        args = parser.parse_args()

        logs_bucket = args.bucket
        s3_cfg = {
            'endpoint_url': args.s3_endpoint_url,
            'access_key': args.s3_access_key,
            'secret_key': args.s3_secret_key
        }
        log_message(f'DEBUG: Получен S3 конфиг {s3_cfg}')

        os.environ['AWS_ACCESS_KEY_ID'] = args.s3_access_key.strip()
        os.environ['AWS_SECRET_ACCESS_KEY'] = args.s3_secret_key.strip()
        os.environ['MLFLOW_S3_ENDPOINT_URL'] = args.s3_endpoint_url.strip()

        spark = create_spark_session(s3_cfg=s3_cfg)

        df, feature_cols = load_data(spark, args.input_data)
        train_df, test_df = stratified_train_test_split(df=df)

        # Обучение модели
        model, _, metrics = train_model(
            train_df=train_df,
            test_df=test_df,
            feature_cols=feature_cols,
            tracking_uri=args.tracking_uri,
            experiment_name=args.experiment_name,
            run_name=args.run_name,
        )

        # Сохранение модели в S3
        save_model_to_s3(model=model, output_path=args.output_model)

        # Детальная аналитика результатов
        log_message('=' * 50)
        log_message('INFO: Обучение успешно завершено!')
        log_message('=' * 50)

        log_message('Значения метрик на тестовой выборке:')
        log_message(f"AUC:      {metrics['test_auc']:.4f}")
        log_message(f"Точность: {metrics['test_acc']:.4f}")
        log_message(f"F1-score: {metrics['test_f1']:.4f}")

    except Exception as e:
        log_message(f'ERROR: КРИТИЧЕСКАЯ ОШИБКА: {e}')
        log_message(f'Traceback:\n{traceback.format_exc()}')
        raise
    finally:
        if spark is not None:
            spark.stop()
        try:
            job_time = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            log_s3_key = f'logs/train_logs/baseline-job-{job_time}.log'

            if logs_bucket and s3_cfg:
                upload_log_to_s3(
                    bucket=logs_bucket,
                    log_key=log_s3_key,
                    s3_cfg=s3_cfg
                )
            else:
                print('WARNING: Не удалось загрузить лог в S3')

        except Exception as e:
            print(f'ERROR: Ошибка при загрузке лога в S3: {e}')


if __name__ == "__main__":
    main()
