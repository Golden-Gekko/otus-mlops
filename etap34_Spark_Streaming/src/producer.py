from argparse import ArgumentParser
from datetime import datetime
import json
import os
import random
import time
import traceback
from typing import Iterator
from urllib.request import urlretrieve

import boto3
from kafka import KafkaProducer

LOG_FILE_PATH = '/tmp/producer_job.log'
YANDEX_CA_URL = 'https://storage.yandexcloud.net/cloud-certs/CA.pem'
DEFAULT_CA_PATH = '/tmp/YandexInternalRootCA.crt'

FEATURE_COLS = [
    'transaction_id',
    'tx_datetime',
    'customer_id',
    'terminal_id',
    'tx_amount',
    'tx_time_seconds',
    'tx_time_days',
    'tx_fraud',
]


def log_message(msg: str) -> None:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{timestamp}] {msg}'
    print(line)
    with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def ensure_yandex_ca(ca_path: str) -> str:
    if os.path.exists(ca_path):
        return ca_path
    target = ca_path if ca_path else DEFAULT_CA_PATH
    os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
    urlretrieve(YANDEX_CA_URL, target)
    return target


def to_boto3_name(path: str) -> str:
    return path.replace('s3://', '').replace('s3a://', '').strip('/')


def load_rows_from_s3_parquet_with_spark(
    spark,
    bucket: str,
    prefix: str,
    max_rows: int = 5000,
) -> list[dict]:
    path = f"s3a://{to_boto3_name(bucket)}/{prefix.strip('/')}"
    df = spark.read.parquet(path).limit(max_rows)
    return [row.asdict(recursive=True) for row in df.collect()]


def load_rows_from_s3_parquet_sample(
    bucket: str,
    prefix: str,
    s3_cfg: dict[str, str],
    max_rows: int = 5000,
) -> list[dict]:
    try:
        from pyspark.sql import SparkSession

        spark = (
            SparkSession.builder
            .appName('KafkaProducerSample')
            .config(
                'spark.hadoop.fs.s3a.impl',
                'org.apache.hadoop.fs.s3a.S3AFileSystem')
            .config('spark.hadoop.fs.s3a.endpoint', s3_cfg['endpoint_url'])
            .config('spark.hadoop.fs.s3a.access.key', s3_cfg['access_key'])
            .config('spark.hadoop.fs.s3a.secret.key', s3_cfg['secret_key'])
            .config('spark.hadoop.fs.s3a.path.style.access', 'true')
            .getOrCreate()
        )
        try:
            return load_rows_from_s3_parquet_with_spark(
                spark, bucket, prefix, max_rows)
        finally:
            spark.stop()
    except Exception as e:
        log_message(f'WARN: Не удалось прочитать parquet через Spark: {e}')
        raise


def load_rows_from_jsonl(path: str, max_rows: int = 5000) -> list[dict]:
    rows: list[dict] = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if len(rows) >= max_rows:
                break
    return rows


def serialize_row(row: dict) -> dict:
    out = {}
    dt_obj = None
    for key in FEATURE_COLS:
        if key not in row:
            continue
        val = row[key]
        if key == 'tx_datetime':
            if hasattr(val, 'strftime'):
                dt_obj = val
                out[key] = val.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(val, str) and val.strip():
                raw = val.strip().replace('T', ' ')
                out[key] = raw.split('.')[0][:19]
                try:
                    dt_obj = datetime.strptime(out[key], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    dt_obj = None
            else:
                out[key] = val
        elif key in (
            'transaction_id', 'customer_id', 'terminal_id',
            'tx_time_seconds', 'tx_time_days', 'tx_fraud',
        ):
            out[key] = int(val) if val is not None else None
        elif key == 'tx_amount':
            out[key] = float(val) if val is not None else None
        elif hasattr(val, 'isoformat'):
            out[key] = val.isoformat()
        else:
            out[key] = val

    # Как Spark dayofweek: 1=Sunday … 7=Saturday
    if dt_obj is not None:
        out['day_of_week'] = (dt_obj.isoweekday() % 7) + 1
        out['month'] = int(dt_obj.month)

    if 'tx_fraud' in row and 'tx_fraud' not in out:
        out['tx_fraud'] = int(row['tx_fraud'])
    out['event_ts'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    return out


def rate_limited(rate: float) -> Iterator[None]:
    interval = 1.0 / rate if rate > 0 else 0.0
    next_ts = time.perf_counter()
    while True:
        now = time.perf_counter()
        sleep_for = next_ts - now
        if sleep_for > 0:
            time.sleep(sleep_for)
        yield
        next_ts += interval


def create_producer(
    bootstrap: str,
    user: str,
    password: str,
    security_protocol: str,
    sasl_mechanism: str,
    ca_path: str,
) -> KafkaProducer:
    servers = [s.strip() for s in bootstrap.split(',') if s.strip()]
    return KafkaProducer(
        bootstrap_servers=servers,
        security_protocol=security_protocol,
        sasl_mechanism=sasl_mechanism,
        ssl_cafile=ca_path,
        sasl_plain_username=user,
        sasl_plain_password=password,
        value_serializer=lambda m: json.dumps(m, default=str).encode('utf-8'),
        linger_ms=5,
        acks=1,
    )


def run_load(
    producer: KafkaProducer,
    topic: str,
    rows: list[dict],
    rate: float,
    duration_sec: float | None,
    limit: int | None,
) -> int:
    sent = 0
    deadline = (
        time.perf_counter() + duration_sec if duration_sec else None
    )
    ticker = rate_limited(rate)
    log_message(
        f'INFO: Старт нагрузки rate={rate} TPS, duration={duration_sec}, limit={limit}')
    try:
        while True:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            if limit is not None and sent >= limit:
                break
            next(ticker)
            row = serialize_row(random.choice(rows))
            producer.send(topic, value=row)
            sent += 1
            if sent % max(int(rate), 1) == 0:
                log_message(f'INFO: Отправлено {sent} сообщений')
    finally:
        producer.flush()
    log_message(f'INFO: Завершено, всего отправлено {sent}')
    return sent


def measure_lag(
    bootstrap: str,
    topic: str,
    group_id: str,
    user: str,
    password: str,
    security_protocol: str,
    sasl_mechanism: str,
    ca_path: str,
    output_topic: str = '',
) -> int:
    stats = collect_topic_stats(
        bootstrap=bootstrap,
        input_topic=topic,
        output_topic=output_topic,
        group_id=group_id,
        user=user,
        password=password,
        security_protocol=security_protocol,
        sasl_mechanism=sasl_mechanism,
        ca_path=ca_path,
    )
    return int(stats['lag'])


def collect_topic_stats(
    bootstrap: str,
    input_topic: str,
    output_topic: str,
    group_id: str,
    user: str,
    password: str,
    security_protocol: str,
    sasl_mechanism: str,
    ca_path: str,
) -> dict:
    from kafka import KafkaConsumer, TopicPartition

    servers = [s.strip() for s in bootstrap.split(',') if s.strip()]
    consumer = KafkaConsumer(
        bootstrap_servers=servers,
        group_id=group_id or 'lag-probe',
        security_protocol=security_protocol,
        sasl_mechanism=sasl_mechanism,
        ssl_cafile=ca_path,
        sasl_plain_username=user,
        sasl_plain_password=password,
    )
    try:
        def end_map(topic_name: str) -> dict[str, object]:
            parts = consumer.partitions_for_topic(topic_name)
            if not parts:
                return {'end': 0, 'partitions': {}}
            tps = [TopicPartition(topic_name, p) for p in parts]
            ends = consumer.end_offsets(tps)
            per = {str(tp.partition): ends[tp] for tp in tps}
            return {'end': int(sum(ends.values())), 'partitions': per}

        inp = end_map(input_topic)
        out = end_map(output_topic) if output_topic else {'end': 0, 'partitions': {}}
        lag = max(int(inp['end']) - int(out['end']), 0)
        return {
            'inputs_end': inp['end'],
            'predictions_end': out['end'],
            'lag': lag,
            'inputs_partitions': inp['partitions'],
            'predictions_partitions': out['partitions'],
        }
    finally:
        consumer.close()


def run_ramp(
    producer: KafkaProducer,
    topic: str,
    rows: list[dict],
    rates: list[float],
    step_duration: float,
    lag_ctx: dict | None = None,
    lag_growth_delta: int = 50,
) -> dict:
    results = {'steps': [], 'lag_growth_threshold_tps': None, 'kafka_topic_stats': None}
    for rate in rates:
        log_message(f'INFO: === Ступень {rate} TPS, {step_duration}s ===')
        lag_before = None
        if lag_ctx:
            lag_before = measure_lag(**lag_ctx)
            log_message(f'INFO: lag_before={lag_before} @ {rate} TPS')

        count = run_load(
            producer, topic, rows, rate, step_duration, limit=None)

        lag_after = None
        growth = None
        if lag_ctx:
            lag_after = measure_lag(**lag_ctx)
            growth = lag_after - (lag_before or 0)
            if (
                growth is not None
                and growth >= lag_growth_delta
                and results['lag_growth_threshold_tps'] is None
            ):
                results['lag_growth_threshold_tps'] = rate
                log_message(
                    f'INFO: Порог роста очереди: {rate} TPS (delta>={lag_growth_delta})'
                )

        results['steps'].append({
            'rate': rate,
            'sent': count,
            'lag_before': lag_before,
            'lag_after': lag_after,
            'lag_growth': growth,
        })
        time.sleep(2)

    if lag_ctx:
        results['kafka_topic_stats'] = collect_topic_stats(
            bootstrap=lag_ctx['bootstrap'],
            input_topic=lag_ctx['topic'],
            output_topic=lag_ctx.get('output_topic') or '',
            group_id=lag_ctx['group_id'],
            user=lag_ctx['user'],
            password=lag_ctx['password'],
            security_protocol=lag_ctx['security_protocol'],
            sasl_mechanism=lag_ctx['sasl_mechanism'],
            ca_path=lag_ctx['ca_path'],
        )
        log_message(f'INFO: kafka_topic_stats={results["kafka_topic_stats"]}')
    return results


def upload_json_to_s3(
    bucket: str, key: str, payload: dict, s3_cfg: dict[str, str]
) -> None:
    if not bucket:
        return
    try:
        s3 = boto3.client(
            's3',
            endpoint_url=s3_cfg['endpoint_url'],
            aws_access_key_id=s3_cfg['access_key'],
            aws_secret_access_key=s3_cfg['secret_key'],
        )
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        s3.put_object(Bucket=to_boto3_name(bucket), Key=key, Body=body)
        log_message(f'INFO: JSON загружен в s3://{bucket}/{key}')
    except Exception as e:
        log_message(f'WARN: Не удалось загрузить JSON: {e}')


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
    except Exception as e:
        log_message(f'WARN: Не удалось загрузить лог: {e}')


def execute_ramp(
    bootstrap_servers: str,
    topic: str,
    kafka_user: str,
    kafka_password: str,
    rows: list[dict],
    rates: list[float],
    step_duration: float,
    security_protocol: str = 'SASL_SSL',
    sasl_mechanism: str = 'SCRAM-SHA-512',
    ssl_cafile: str = DEFAULT_CA_PATH,
    lag_group_id: str = 'spark-fraud-infer',
    lag_kafka_user: str = '',
    lag_kafka_password: str = '',
    output_topic: str = 'predictions',
    lag_growth_delta: int = 50,
    bucket: str = '',
    s3_cfg: dict[str, str] | None = None,
) -> dict:
    if not rows:
        raise RuntimeError('Нет данных для генерации потока')
    ca_path = ensure_yandex_ca(ssl_cafile)
    log_message(f'INFO: Загружено {len(rows)} строк для сэмплирования')
    producer = create_producer(
        bootstrap_servers,
        kafka_user,
        kafka_password,
        security_protocol,
        sasl_mechanism,
        ca_path,
    )
    lag_user = lag_kafka_user or kafka_user
    lag_password = lag_kafka_password or kafka_password
    lag_ctx = {
        'bootstrap': bootstrap_servers,
        'topic': topic,
        'group_id': lag_group_id,
        'user': lag_user,
        'password': lag_password,
        'security_protocol': security_protocol,
        'sasl_mechanism': sasl_mechanism,
        'ca_path': ca_path,
        'output_topic': output_topic,
    }
    try:
        ramp_result = run_ramp(
            producer,
            topic,
            rows,
            rates,
            step_duration,
            lag_ctx=lag_ctx,
            lag_growth_delta=lag_growth_delta,
        )
        if bucket and s3_cfg:
            upload_json_to_s3(
                bucket,
                f'metrics/ramp_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json',
                ramp_result,
                s3_cfg,
            )
            upload_log_to_s3(
                bucket,
                f'logs/producer/producer_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.log',
                s3_cfg,
            )
        return ramp_result
    finally:
        producer.close()


def main() -> None:
    parser = ArgumentParser(description='Kafka load producer for fraud txs')
    parser.add_argument('--bootstrap_servers', required=True)
    parser.add_argument('--topic', required=True)
    parser.add_argument('--kafka_user', required=True)
    parser.add_argument('--kafka_password', required=True)
    parser.add_argument('--security_protocol', default='SASL_SSL')
    parser.add_argument('--sasl_mechanism', default='SCRAM-SHA-512')
    parser.add_argument('--ssl_cafile', default=DEFAULT_CA_PATH)
    parser.add_argument('--rate', type=float, default=50.0)
    parser.add_argument('--duration', type=float, default=60.0)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument(
        '--ramp',
        default='',
        help='Список TPS через запятую, напр. 50,100,200,400',
    )
    parser.add_argument('--step_duration', type=float, default=60.0)
    parser.add_argument('--bucket', default='')
    parser.add_argument('--data_prefix', default='cleaned_data')
    parser.add_argument('--local_jsonl', default='')
    parser.add_argument('--s3_endpoint_url', default='https://storage.yandexcloud.net')
    parser.add_argument('--s3_access_key', default='')
    parser.add_argument('--s3_secret_key', default='')
    parser.add_argument('--max_sample_rows', type=int, default=5000)
    parser.add_argument('--lag_group_id', default='spark-fraud-infer')
    parser.add_argument('--lag_kafka_user', default='')
    parser.add_argument('--lag_kafka_password', default='')
    parser.add_argument('--lag_growth_delta', type=int, default=50)
    parser.add_argument('--output_topic', default='predictions')
    args = parser.parse_args()

    try:
        ca_path = ensure_yandex_ca(args.ssl_cafile)
        s3_cfg = {
            'endpoint_url': args.s3_endpoint_url,
            'access_key': args.s3_access_key,
            'secret_key': args.s3_secret_key,
        }

        if args.local_jsonl:
            rows = load_rows_from_jsonl(args.local_jsonl, args.max_sample_rows)
        else:
            if not args.bucket:
                raise ValueError('Укажите --bucket или --local_jsonl')
            rows = load_rows_from_s3_parquet_sample(
                args.bucket, args.data_prefix, s3_cfg, args.max_sample_rows)

        if not rows:
            raise RuntimeError('Нет данных для генерации потока')

        log_message(f'INFO: Загружено {len(rows)} строк для сэмплирования')
        producer = create_producer(
            args.bootstrap_servers,
            args.kafka_user,
            args.kafka_password,
            args.security_protocol,
            args.sasl_mechanism,
            ca_path,
        )

        lag_user = args.lag_kafka_user or args.kafka_user
        lag_password = args.lag_kafka_password or args.kafka_password
        lag_ctx = {
            'bootstrap': args.bootstrap_servers,
            'topic': args.topic,
            'group_id': args.lag_group_id,
            'user': lag_user,
            'password': lag_password,
            'security_protocol': args.security_protocol,
            'sasl_mechanism': args.sasl_mechanism,
            'ca_path': ca_path,
            'output_topic': args.output_topic,
        }

        try:
            if args.ramp.strip():
                rates = [float(x) for x in args.ramp.split(',') if x.strip()]
                ramp_result = run_ramp(
                    producer,
                    args.topic,
                    rows,
                    rates,
                    args.step_duration,
                    lag_ctx=lag_ctx,
                    lag_growth_delta=args.lag_growth_delta,
                )
                if args.bucket:
                    upload_json_to_s3(
                        args.bucket,
                        'metrics/ramp_'
                        f'{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json',
                        ramp_result,
                        s3_cfg,
                    )
            else:
                run_load(
                    producer,
                    args.topic,
                    rows,
                    args.rate,
                    args.duration,
                    args.limit,
                )
        finally:
            producer.close()

        if args.bucket:
            upload_log_to_s3(
                args.bucket,
                f'logs/producer/producer_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.log',
                s3_cfg,
            )
    except Exception:
        log_message(f'ERROR: {traceback.format_exc()}')
        raise


if __name__ == '__main__':
    main()
