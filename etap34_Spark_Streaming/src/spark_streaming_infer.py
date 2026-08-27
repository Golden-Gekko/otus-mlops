from argparse import ArgumentParser
from datetime import datetime
import importlib.util
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
from urllib.request import urlretrieve

import boto3
from botocore.exceptions import ClientError
import mlflow
from mlflow.tracking import MlflowClient
from pyspark import SparkFiles
from pyspark.ml import PipelineModel
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import (
    col, coalesce, current_timestamp, dayofweek, from_json, lit, month, struct,
    to_json, to_timestamp)
from pyspark.ml.functions import vector_to_array
from pyspark.sql.types import (
    DoubleType, IntegerType, LongType, StringType, StructField, StructType)
from pyspark.sql.utils import StreamingQueryException

LOG_FILE_PATH = '/tmp/spark_streaming_infer.log'
YANDEX_CA_URL = 'https://storage.yandexcloud.net/cloud-certs/CA.pem'
DEFAULT_CA_PATH = '/tmp/YandexInternalRootCA.crt'
DEFAULT_JKS_PATH = '/tmp/YandexInternalRootCA.jks'
JKS_STORE_PASSWORD = 'changeit'
JKS_FILENAME = 'YandexInternalRootCA.jks'
MODEL_NAME = 'fraud_detection_rf'
CHAMPION_TAG = 'champion'
DEFAULT_PRODUCER_DELAY_SEC = 45


def log_message(msg: str) -> None:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{timestamp}] {msg}'
    print(line)
    with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def to_boto3_name(path: str) -> str:
    return path.replace('s3://', '').replace('s3a://', '').strip('/')


def ensure_yandex_ca(ca_path: str) -> str:
    if os.path.exists(ca_path):
        return ca_path
    target = ca_path or DEFAULT_CA_PATH
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    log_message(f'INFO: Скачивание Yandex CA в {target}')
    urlretrieve(YANDEX_CA_URL, target)
    return target


def pem_to_jks(pem_path: str, jks_path: str = DEFAULT_JKS_PATH) -> str:
    if os.path.exists(jks_path):
        try:
            os.remove(jks_path)
        except OSError:
            pass
    parent = os.path.dirname(jks_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    cmd = [
        'keytool',
        '-importcert',
        '-noprompt',
        '-alias', 'YandexInternalRootCA',
        '-file', pem_path,
        '-keystore', jks_path,
        '-storepass', JKS_STORE_PASSWORD,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f'keytool failed ({result.returncode}): {result.stderr or result.stdout}'
        )
    log_message(f'INFO: JKS truststore готов: {jks_path}')
    return jks_path


def distribute_truststore(spark: SparkSession, jks_path: str) -> str:
    spark.sparkContext.addFile(jks_path)
    jks_filename = JKS_FILENAME
    target_path = DEFAULT_JKS_PATH

    def _copy_to_tmp(_iterator):
        src = SparkFiles.get(jks_filename)
        parent = os.path.dirname(target_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy(src, target_path)
        yield os.path.exists(target_path), os.path.getsize(target_path)

    n_parts = max(spark.sparkContext.defaultParallelism, 2)
    results = (
        spark.sparkContext
        .parallelize(range(n_parts), n_parts)
        .mapPartitions(_copy_to_tmp)
        .collect()
    )
    log_message(
        f'INFO: Truststore скопирован на executors -> {target_path}, results={results}')
    if not os.path.exists(target_path):
        raise RuntimeError(f'Truststore отсутствует на driver: {target_path}')
    return target_path


def mask_kafka_options(opts: dict[str, str]) -> dict[str, str]:
    masked = dict(opts)
    if 'kafka.ssl.truststore.password' in masked:
        masked['kafka.ssl.truststore.password'] = '***'
    jaas = masked.get('kafka.sasl.jaas.config', '')
    if jaas:
        masked['kafka.sasl.jaas.config'] = re.sub(r'password="[^"]*"', 'password="***"', jaas)
    return masked


def log_kafka_setup(
    truststore_path: str,
    read_opts: dict[str, str],
    write_opts: dict[str, str],
    group_id: str,
) -> None:
    exists = os.path.exists(truststore_path)
    size = os.path.getsize(truststore_path) if exists else -1
    log_message(
        f'INFO: Kafka truststore path={truststore_path} exists={exists} size={size} cwd={os.getcwd()}')
    log_message(
        f'INFO: Kafka group_id={group_id} '
        f'bootstrap={read_opts.get("kafka.bootstrap.servers")} '
        f'input_subscribe={read_opts.get("subscribe")} '
        f'security={read_opts.get("kafka.security.protocol")} '
        f'sasl={read_opts.get("kafka.sasl.mechanism")}'
    )
    log_message(f'INFO: Kafka read options: {mask_kafka_options(read_opts)}')
    log_message(f'INFO: Kafka write options: {mask_kafka_options(write_opts)}')


def upload_log_to_s3(bucket: str, log_key: str, s3_cfg: dict[str, str]) -> None:
    if not os.path.exists(LOG_FILE_PATH) or not bucket:
        return
    try:
        s3 = boto3.client(
            's3',
            endpoint_url=s3_cfg['endpoint_url'],
            aws_access_key_id=s3_cfg['access_key'],
            aws_secret_access_key=s3_cfg['secret_key'],
        )
        s3.upload_file(LOG_FILE_PATH, to_boto3_name(bucket), log_key)
        log_message(f'INFO: Лог загружен в s3://{bucket}/{log_key}')
    except ClientError as e:
        log_message(f'WARN: Ошибка загрузки лога: {e}')


def load_src_module(module_name: str, bucket: str, s3_cfg: dict[str, str]):
    local_path = f'/tmp/{module_name}.py'
    s3 = boto3.client(
        's3',
        endpoint_url=s3_cfg['endpoint_url'],
        aws_access_key_id=s3_cfg['access_key'],
        aws_secret_access_key=s3_cfg['secret_key'],
    )
    key = f'src/{module_name}.py'
    log_message(f'INFO: Загрузка модуля s3://{bucket}/{key} -> {local_path}')
    s3.download_file(to_boto3_name(bucket), key, local_path)
    spec = importlib.util.spec_from_file_location(module_name, local_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Не удалось загрузить модуль {module_name}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def create_spark_session(s3_cfg: dict[str, str], app_name: str) -> SparkSession:
    builder = (
        SparkSession.builder
        .appName(app_name)
        .config(
            'spark.hadoop.fs.s3a.impl',
            'org.apache.hadoop.fs.s3a.S3AFileSystem')
        .config('spark.hadoop.fs.s3a.endpoint', s3_cfg['endpoint_url'])
        .config('spark.hadoop.fs.s3a.access.key', s3_cfg['access_key'])
        .config('spark.hadoop.fs.s3a.secret.key', s3_cfg['secret_key'])
        .config('spark.hadoop.fs.s3a.path.style.access', 'true')
        .config('spark.hadoop.fs.s3a.connection.ssl.enabled', 'true')
        .config('spark.sql.streaming.checkpointLocation', '/tmp/ss_checkpoint')
    )
    return builder.getOrCreate()


def resolve_champion_model_uri(
    tracking_uri: str,
    model_name: str = MODEL_NAME,
    stage_tag: str = CHAMPION_TAG,
) -> str:
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient()

    try:
        mv = client.get_model_version_by_alias(model_name, stage_tag)
        uri = f'models:/{model_name}@{stage_tag}'
        log_message(f'INFO: Модель по alias @{stage_tag}: version={mv.version}')
        return uri
    except Exception as e:
        log_message(f'WARN: Alias @{stage_tag} не найден: {e}')

    versions = client.search_model_versions(f"name='{model_name}'")
    champions = [
        v for v in versions
        if (v.tags or {}).get('stage') == stage_tag
        or (v.tags or {}).get('alias') == stage_tag
    ]
    if champions:
        best = sorted(champions, key=lambda v: int(v.version), reverse=True)[0]
        uri = f'models:/{model_name}/{best.version}'
        log_message(f'INFO: Модель по тегу stage={stage_tag}: {uri}')
        return uri

    if versions:
        best = sorted(versions, key=lambda v: int(v.version), reverse=True)[0]
        uri = f'models:/{model_name}/{best.version}'
        return uri

    raise RuntimeError(f'В Registry нет модели {model_name}')


def load_pipeline_model(
    model_uri: str,
    s3_cfg: dict[str, str],
) -> PipelineModel:
    os.environ['AWS_ACCESS_KEY_ID'] = s3_cfg['access_key'].strip()
    os.environ['AWS_SECRET_ACCESS_KEY'] = s3_cfg['secret_key'].strip()
    os.environ['MLFLOW_S3_ENDPOINT_URL'] = s3_cfg['endpoint_url'].strip()
    os.environ['AWS_DEFAULT_REGION'] = 'ru-central1'

    log_message(
        f'INFO: S3 endpoint для MLflow={os.environ["MLFLOW_S3_ENDPOINT_URL"]}, '
        f'key_prefix={os.environ["AWS_ACCESS_KEY_ID"][:8]}...'
    )
    log_message(f'INFO: Загрузка PipelineModel из {model_uri}')

    # Сначала скачиваем артефакт локально через boto3 с явным endpoint
    local_dir = mlflow.artifacts.download_artifacts(artifact_uri=model_uri)
    log_message(f'INFO: Артефакт скачан')
    model = mlflow.spark.load_model(local_dir)
    return model


def input_schema() -> StructType:
    return StructType([
        StructField('transaction_id', LongType(), True),
        StructField('tx_datetime', StringType(), True),
        StructField('customer_id', LongType(), True),
        StructField('terminal_id', LongType(), True),
        StructField('tx_amount', DoubleType(), True),
        StructField('tx_time_seconds', LongType(), True),
        StructField('tx_time_days', LongType(), True),
        StructField('tx_fraud', IntegerType(), True),
        StructField('event_ts', StringType(), True),
        StructField('day_of_week', IntegerType(), True),
        StructField('month', IntegerType(), True),
    ])


def prepare_features(df: DataFrame) -> DataFrame:
    df = df.withColumn('target', col('tx_fraud').cast('int'))
    ts = to_timestamp(col('tx_datetime'), 'yyyy-MM-dd HH:mm:ss')
    day = coalesce(
        col('day_of_week').cast('int'),
        dayofweek(ts),
        ((col('tx_time_days') % 7) + 1).cast('int'),
    )
    month_col = coalesce(
        col('month').cast('int'),
        month(ts),
        lit(1),
    )
    df = df.withColumn('day_of_week', day)
    df = df.withColumn('month', month_col)
    return df


FEATURE_DEBUG_COLS = [
    'transaction_id',
    'tx_datetime',
    'customer_id',
    'terminal_id',
    'tx_amount',
    'tx_time_days',
    'tx_fraud',
    'day_of_week',
    'month',
]
MODEL_FEATURE_COLS = [
    'customer_id',
    'tx_amount',
    'tx_time_days',
    'terminal_id',
    'day_of_week',
    'month',
]


def log_empty_transform_debug(batch_df: DataFrame, batch_id: int, in_count: int) -> None:
    try:
        log_message(
            f'WARN: batch={batch_id} transform empty: in_rows={in_count} '
            f'schema={batch_df.schema.simpleString()}'
        )
        log_message(f'WARN: batch={batch_id} dtypes={batch_df.dtypes}')
        present = [c for c in FEATURE_DEBUG_COLS if c in batch_df.columns]
        sample_rows = (
            batch_df.select(*present).limit(5).collect()
            if present else batch_df.limit(5).collect()
        )
        for i, row in enumerate(sample_rows):
            log_message(f'WARN: batch={batch_id} raw_row[{i}]={row.asdict(recursive=True)}')
        null_bits = []
        for c in MODEL_FEATURE_COLS:
            if c not in batch_df.columns:
                null_bits.append(f'{c}=<missing>')
                continue
            n_null = batch_df.filter(col(c).isNull()).count()
            null_bits.append(f'{c}_null={n_null}/{in_count}')
        log_message(
            f'WARN: batch={batch_id} null_summary in_rows={in_count} out_rows=0 {" ".join(null_bits)}'
        )
    except Exception as e:
        log_message(f'WARN: batch={batch_id} debug log failed: {e}')


def build_kafka_options(
    bootstrap: str,
    topic: str,
    user: str,
    password: str,
    security_protocol: str,
    sasl_mechanism: str,
    truststore_path: str,
    starting_offsets: str = 'latest',
) -> dict[str, str]:
    jaas = (
        'org.apache.kafka.common.security.scram.ScramLoginModule required '
        f'username="{user}" password="{password}";'
    )
    return {
        'kafka.bootstrap.servers': bootstrap,
        'subscribe': topic,
        'startingOffsets': starting_offsets,
        'kafka.security.protocol': security_protocol,
        'kafka.sasl.mechanism': sasl_mechanism,
        'kafka.sasl.jaas.config': jaas,
        'kafka.ssl.truststore.location': truststore_path,
        'kafka.ssl.truststore.password': JKS_STORE_PASSWORD,
        'kafka.ssl.endpoint.identification.algorithm': '',
        'failOnDataLoss': 'false',
    }


def run_streaming(
    spark: SparkSession,
    model: PipelineModel,
    read_opts: dict[str, str],
    write_opts: dict[str, str],
    output_topic: str,
    duration_sec: int,
    checkpoint: str,
    on_started=None,
) -> int:
    written_total = {'n': 0}

    raw = (
        spark.readStream
        .format('kafka')
        .options(**read_opts)
        .load()
    )

    parsed = (
        raw
        .selectExpr('CAST(value AS STRING) AS json_str')
        .select(from_json(col('json_str'), input_schema()).alias('data'))
        .select('data.*')
        .filter(col('tx_amount').isNotNull())
    )

    featured = prepare_features(parsed)

    def process_batch(batch_df: DataFrame, batch_id: int) -> None:
        if batch_df.rdd.isEmpty():
            log_message(f'INFO: batch={batch_id} пустой')
            return
        in_count = batch_df.count()
        log_message(f'INFO: batch={batch_id}, in_rows={in_count}')
        preds = model.transform(batch_df)
        out_count = preds.count()
        log_message(f'INFO: batch={batch_id}, out_rows={out_count}')
        if in_count > 0 and out_count == 0:
            log_empty_transform_debug(batch_df, batch_id, in_count)
            log_message(
                f'WARN: batch={batch_id}: transform=0, skip write '
                f'(не роняем query)'
            )
            return
        out = preds.select(
            to_json(struct(
                col('transaction_id'),
                col('tx_fraud').alias('gt'),
                col('prediction'),
                vector_to_array(col('probability'))[1].alias('probability'),
                current_timestamp().alias('inferred_at'),
            )).alias('value')
        )
        (
            out.write
            .format('kafka')
            .options(**write_opts)
            .option('topic', output_topic)
            .save()
        )
        written_total['n'] += out_count
        log_message(f'INFO: batch={batch_id}, written={out_count}')

    query = (
        featured.writeStream
        .foreachBatch(process_batch)
        .option('checkpointLocation', checkpoint)
        .start()
    )

    log_message(f'INFO: Streaming запущен на {duration_sec} секунд')
    if on_started is not None:
        on_started()
    try:
        query.awaitTermination(duration_sec)
    except StreamingQueryException as exc:
        q_exc = None
        try:
            q_exc = query.exception()
        except Exception:
            pass
        log_message(f'ERROR: StreamingQueryException: {exc}')
        if q_exc is not None:
            log_message(f'ERROR: query.exception(): {q_exc}')
        raise
    if query.isActive:
        log_message('INFO: Останавливаем streaming по таймауту')
        query.stop()
    log_message(f'INFO: Streaming завершён, written_total={written_total["n"]}')
    return written_total['n']


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument('--bootstrap_servers', required=True)
    parser.add_argument('--input_topic', required=True)
    parser.add_argument('--output_topic', required=True)
    parser.add_argument('--kafka_user', required=True)
    parser.add_argument('--kafka_password', required=True)
    parser.add_argument('--security_protocol', default='SASL_SSL')
    parser.add_argument('--sasl_mechanism', default='SCRAM-SHA-512')
    parser.add_argument('--ssl_cafile', default=DEFAULT_CA_PATH)
    parser.add_argument('--tracking_uri', required=True)
    parser.add_argument('--model_name', default=MODEL_NAME)
    parser.add_argument('--champion_tag', default=CHAMPION_TAG)
    parser.add_argument('--duration_sec', type=int, default=600)
    parser.add_argument('--checkpoint', default='/tmp/ss_checkpoint_infer')
    parser.add_argument('--bucket', default='')
    parser.add_argument('--s3_endpoint_url', default='https://storage.yandexcloud.net')
    parser.add_argument('--s3_access_key', default='')
    parser.add_argument('--s3_secret_key', default='')
    parser.add_argument('--group_id', default='spark-fraud-infer')
    parser.add_argument('--run_producer', type=int, default=1)
    parser.add_argument('--producer_user', default='')
    parser.add_argument('--producer_password', default='')
    parser.add_argument('--producer_delay_sec', type=int, default=DEFAULT_PRODUCER_DELAY_SEC)
    parser.add_argument('--ramp', default='50,100,200,400')
    parser.add_argument('--step_duration', type=float, default=60.0)
    parser.add_argument('--data_prefix', default='cleaned_data')
    parser.add_argument('--max_sample_rows', type=int, default=5000)
    parser.add_argument('--run_evaluate', type=int, default=1)
    parser.add_argument('--eval_rounds', type=int, default=2)
    parser.add_argument('--eval_measure_interval_sec', type=float, default=10.0)
    parser.add_argument('--lag_growth_delta', type=int, default=50)
    args = parser.parse_args()

    spark: SparkSession | None = None
    s3_cfg = {
        'endpoint_url': args.s3_endpoint_url,
        'access_key': args.s3_access_key,
        'secret_key': args.s3_secret_key,
    }
    if not args.s3_access_key or not args.s3_secret_key:
        raise ValueError('Нужны --s3_access_key и --s3_secret_key для MLflow artifacts')
    if not args.bucket:
        raise ValueError('Нужен --bucket для модулей producer/evaluate и логов')

    os.environ['AWS_ACCESS_KEY_ID'] = args.s3_access_key.strip()
    os.environ['AWS_SECRET_ACCESS_KEY'] = args.s3_secret_key.strip()
    os.environ['MLFLOW_S3_ENDPOINT_URL'] = args.s3_endpoint_url.strip()
    os.environ['AWS_DEFAULT_REGION'] = 'ru-central1'

    producer_error: list[BaseException] = []
    producer_thread: threading.Thread | None = None

    try:
        ca_path = ensure_yandex_ca(args.ssl_cafile)
        jks_path = pem_to_jks(ca_path, DEFAULT_JKS_PATH)
        spark = create_spark_session(s3_cfg, 'FraudStreamingInference')
        truststore_path = distribute_truststore(spark, jks_path)
        model_uri = resolve_champion_model_uri(
            args.tracking_uri, args.model_name, args.champion_tag)
        model = load_pipeline_model(model_uri, s3_cfg)

        read_opts = build_kafka_options(
            args.bootstrap_servers,
            args.input_topic,
            args.kafka_user,
            args.kafka_password,
            args.security_protocol,
            args.sasl_mechanism,
            truststore_path,
            starting_offsets='latest',
        )
        read_opts['kafka.group.id'] = args.group_id

        write_opts = build_kafka_options(
            args.bootstrap_servers,
            args.output_topic,
            args.kafka_user,
            args.kafka_password,
            args.security_protocol,
            args.sasl_mechanism,
            truststore_path,
        )
        write_opts.pop('subscribe', None)
        write_opts.pop('startingOffsets', None)
        write_opts.pop('failOnDataLoss', None)

        log_kafka_setup(truststore_path, read_opts, write_opts, args.group_id)

        sample_rows: list[dict] = []
        if args.run_producer:
            producer_mod = load_src_module('producer', args.bucket, s3_cfg)
            sample_rows = producer_mod.load_rows_from_s3_parquet_with_spark(
                spark,
                args.bucket,
                args.data_prefix,
                args.max_sample_rows,
            )
            log_message(f'INFO: Сэмпл producer: {len(sample_rows)} строк')

            rates = [float(x) for x in args.ramp.split(',') if x.strip()]
            prod_user = args.producer_user or args.kafka_user
            prod_password = args.producer_password or args.kafka_password

            def _producer_worker() -> None:
                try:
                    log_message(f'INFO: Прогрев streaming {args.producer_delay_sec} сек')
                    time.sleep(args.producer_delay_sec)
                    log_message('INFO: Старт Producer ramp')
                    producer_mod.execute_ramp(
                        bootstrap_servers=args.bootstrap_servers,
                        topic=args.input_topic,
                        kafka_user=prod_user,
                        kafka_password=prod_password,
                        rows=sample_rows,
                        rates=rates,
                        step_duration=args.step_duration,
                        security_protocol=args.security_protocol,
                        sasl_mechanism=args.sasl_mechanism,
                        ssl_cafile=ca_path,
                        lag_group_id=args.group_id,
                        lag_kafka_user=args.kafka_user,
                        lag_kafka_password=args.kafka_password,
                        output_topic=args.output_topic,
                        lag_growth_delta=args.lag_growth_delta,
                        bucket=args.bucket,
                        s3_cfg=s3_cfg,
                    )
                    log_message('INFO: Producer ramp завершён')
                except BaseException as exc:
                    log_message(f'ERROR: Producer thread failed: {exc}')
                    producer_error.append(exc)

            def _on_started() -> None:
                nonlocal producer_thread
                producer_thread = threading.Thread(
                    target=_producer_worker,
                    name='kafka-producer-ramp',
                    daemon=True,
                )
                producer_thread.start()
                log_message('INFO: Producer thread запущен')
        else:
            def _on_started() -> None:
                return None

        written_total = run_streaming(
            spark,
            model,
            read_opts,
            write_opts,
            args.output_topic,
            args.duration_sec,
            args.checkpoint,
            on_started=_on_started,
        )
        if written_total == 0:
            raise RuntimeError('Streaming завершился с written_total=0')

        if producer_thread is not None:
            log_message('INFO: Ждём завершения producer thread...')
            producer_thread.join(timeout=120)
            if producer_thread.is_alive():
                log_message('WARN: Producer thread ещё работает после join timeout')
            if producer_error:
                raise RuntimeError(
                    f'Producer failed: {producer_error[0]}'
                ) from producer_error[0]

        if args.run_evaluate:
            log_message('INFO: Запуск evaluate в том же job')
            eval_mod = load_src_module('evaluate_throughput', args.bucket, s3_cfg)
            eval_rates = [float(x) for x in args.ramp.split(',') if x.strip()]
            eval_mod.execute_evaluation(
                bootstrap_servers=args.bootstrap_servers,
                input_topic=args.input_topic,
                output_topic=args.output_topic,
                kafka_user=args.kafka_user,
                kafka_password=args.kafka_password,
                rates=eval_rates,
                group_id=args.group_id,
                security_protocol=args.security_protocol,
                sasl_mechanism=args.sasl_mechanism,
                ssl_cafile=ca_path,
                measure_interval_sec=args.eval_measure_interval_sec,
                rounds=args.eval_rounds,
                lag_growth_delta=args.lag_growth_delta,
                bucket=args.bucket,
                s3_cfg=s3_cfg,
            )
    except Exception:
        log_message(f'ERROR: {traceback.format_exc()}')
        raise
    finally:
        if args.bucket:
            upload_log_to_s3(
                args.bucket,
                f'logs/stream/streaming_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.log',
                s3_cfg,
            )
        if spark is not None:
            spark.stop()


if __name__ == '__main__':
    main()
