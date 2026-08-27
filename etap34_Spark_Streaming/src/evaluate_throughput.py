from argparse import ArgumentParser
from datetime import datetime
import json
import os
import time
import traceback
from urllib.request import urlretrieve

import boto3
from kafka import KafkaConsumer, TopicPartition

LOG_FILE_PATH = '/tmp/evaluate_throughput.log'
YANDEX_CA_URL = 'https://storage.yandexcloud.net/cloud-certs/CA.pem'
DEFAULT_CA_PATH = '/tmp/YandexInternalRootCA.crt'


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
        print(f'INFO: Лог загружен в s3://{bucket}/{log_key}')
    except Exception as e:
        print(f'WARN: Не удалось загрузить лог в S3: {e}')


def kafka_common_kwargs(
    bootstrap: str,
    user: str,
    password: str,
    security_protocol: str,
    sasl_mechanism: str,
    ca_path: str,
) -> dict:
    servers = [s.strip() for s in bootstrap.split(',') if s.strip()]
    return {
        'bootstrap_servers': servers,
        'security_protocol': security_protocol,
        'sasl_mechanism': sasl_mechanism,
        'ssl_cafile': ca_path,
        'sasl_plain_username': user,
        'sasl_plain_password': password,
    }


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
) -> tuple[int, dict[int, int]]:
    kwargs = kafka_common_kwargs(
        bootstrap, user, password, security_protocol, sasl_mechanism, ca_path)

    consumer = KafkaConsumer(group_id=group_id or 'lag-probe', **kwargs)
    try:
        def end_sum(topic_name: str) -> tuple[int, dict[int, int]]:
            partitions = consumer.partitions_for_topic(topic_name)
            if not partitions:
                return 0, {}
            tps = [TopicPartition(topic_name, p) for p in partitions]
            end_offsets = consumer.end_offsets(tps)
            per = {tp.partition: end_offsets[tp] for tp in tps}
            return int(sum(end_offsets.values())), per

        input_end, per_in = end_sum(topic)
        if output_topic:
            output_end, _ = end_sum(output_topic)
            return max(input_end - output_end, 0), per_in
        return input_end, per_in
    finally:
        consumer.close()


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
    kwargs = kafka_common_kwargs(
        bootstrap, user, password, security_protocol, sasl_mechanism, ca_path)
    consumer = KafkaConsumer(group_id=group_id or 'topic-stats', **kwargs)
    try:
        def end_map(topic_name: str) -> dict[str, object]:
            partitions = consumer.partitions_for_topic(topic_name)
            if not partitions:
                return {'end': 0, 'partitions': {}}
            tps = [TopicPartition(topic_name, p) for p in partitions]
            end_offsets = consumer.end_offsets(tps)
            per = {str(tp.partition): end_offsets[tp] for tp in tps}
            return {'end': int(sum(end_offsets.values())), 'partitions': per}

        inp = end_map(input_topic)
        out = end_map(output_topic) if output_topic else {
            'end': 0, 'partitions': {}}
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


def sample_predictions_accuracy(
    bootstrap: str,
    topic: str,
    user: str,
    password: str,
    security_protocol: str,
    sasl_mechanism: str,
    ca_path: str,
    max_messages: int = 200,
    timeout_sec: float = 20.0,
) -> dict[str, float] | None:
    kwargs = kafka_common_kwargs(
        bootstrap, user, password, security_protocol, sasl_mechanism, ca_path)
    consumer = KafkaConsumer(
        topic,
        auto_offset_reset='earliest',
        enable_auto_commit=False,
        consumer_timeout_ms=int(timeout_sec * 1000),
        value_deserializer=lambda b: json.loads(b.decode('utf-8')),
        **kwargs,
    )
    correct = 0
    total = 0
    try:
        for msg in consumer:
            payload = msg.value
            if 'gt' not in payload or 'prediction' not in payload:
                continue
            total += 1
            if int(payload['gt']) == int(float(payload['prediction'])):
                correct += 1
            if total >= max_messages:
                break
    finally:
        consumer.close()

    if total == 0:
        return None
    return {
        'sample_size': float(total),
        'accuracy': correct / total,
    }


def find_lag_threshold(
    history: list[dict],
    lag_growth_delta: int = 50,
) -> float | None:
    threshold = None
    for point in history:
        growth = point['lag_after'] - point['lag_before']
        point['lag_growth'] = growth
        if growth >= lag_growth_delta:
            if threshold is None:
                threshold = point['rate']
    return threshold


def upload_results(
    bucket: str,
    key: str,
    payload: dict,
    s3_cfg: dict[str, str],
) -> None:
    if not bucket:
        return
    s3 = boto3.client(
        's3',
        endpoint_url=s3_cfg['endpoint_url'],
        aws_access_key_id=s3_cfg['access_key'],
        aws_secret_access_key=s3_cfg['secret_key'],
    )
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    s3.put_object(Bucket=to_boto3_name(bucket), Key=key, Body=body)
    log_message(f'INFO: Результат сохранён в s3://{bucket}/{key}')


def execute_evaluation(
    bootstrap_servers: str,
    input_topic: str,
    output_topic: str,
    kafka_user: str,
    kafka_password: str,
    rates: list[float],
    group_id: str = 'spark-fraud-infer',
    security_protocol: str = 'SASL_SSL',
    sasl_mechanism: str = 'SCRAM-SHA-512',
    ssl_cafile: str = DEFAULT_CA_PATH,
    measure_interval_sec: float = 15.0,
    rounds: int = 1,
    lag_growth_delta: int = 50,
    assumed_rate: float | None = None,
    bucket: str = '',
    s3_cfg: dict[str, str] | None = None,
) -> dict:
    s3_cfg = s3_cfg or {}
    log_ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    try:
        log_message(
            f'INFO: evaluate start bootstrap={bootstrap_servers} '
            f'input={input_topic} output={output_topic} '
            f'group_id={group_id} user={kafka_user} '
            f'security={security_protocol} sasl={sasl_mechanism} '
            f'rates={rates} rounds={rounds} '
            f'measure_interval_sec={measure_interval_sec} '
            f'bucket={bucket or "-"}'
        )
        ca_path = ensure_yandex_ca(ssl_cafile)
        log_message(f'INFO: CA path={ca_path} exists={os.path.exists(ca_path)}')
        history: list[dict] = []
        measure_rates = [assumed_rate] if assumed_rate is not None else rates
        log_message(f'INFO: measure_rates={measure_rates}')

        for rate in measure_rates:
            for round_idx in range(rounds):
                lag_before, parts_before = measure_lag(
                    bootstrap_servers,
                    input_topic,
                    group_id,
                    kafka_user,
                    kafka_password,
                    security_protocol,
                    sasl_mechanism,
                    ca_path,
                    output_topic=output_topic,
                )
                log_message(
                    f'INFO: rate={rate} round={round_idx} '
                    f'lag_before={lag_before} parts={parts_before}'
                )
                time.sleep(measure_interval_sec)
                lag_after, parts_after = measure_lag(
                    bootstrap_servers,
                    input_topic,
                    group_id,
                    kafka_user,
                    kafka_password,
                    security_protocol,
                    sasl_mechanism,
                    ca_path,
                    output_topic=output_topic,
                )
                point = {
                    'rate': rate,
                    'round': round_idx,
                    'lag_before': lag_before,
                    'lag_after': lag_after,
                    'parts_before': parts_before,
                    'parts_after': parts_after,
                    'measured_at': datetime.utcnow().isoformat(),
                }
                history.append(point)
                log_message(
                    f'INFO: rate={rate} lag_after={lag_after} '
                    f'growth={lag_after - lag_before}'
                )

        threshold = find_lag_threshold(history, lag_growth_delta)
        quality = sample_predictions_accuracy(
            bootstrap_servers,
            output_topic,
            kafka_user,
            kafka_password,
            security_protocol,
            sasl_mechanism,
            ca_path,
        )
        kafka_topic_stats = collect_topic_stats(
            bootstrap_servers,
            input_topic,
            output_topic,
            group_id,
            kafka_user,
            kafka_password,
            security_protocol,
            sasl_mechanism,
            ca_path,
        )
        log_message(f'INFO: kafka_topic_stats={kafka_topic_stats}')

        result = {
            'history': history,
            'lag_growth_threshold_tps': threshold,
            'lag_growth_delta': lag_growth_delta,
            'quality': quality,
            'kafka_topic_stats': kafka_topic_stats,
            'conclusion': (
                f'Очередь начинает расти примерно при {threshold} TPS'
                if threshold is not None
                else 'При измеренных ступенях устойчивого роста очереди не зафиксировано'
            ),
        }
        log_message(f'INFO: {result["conclusion"]}')
        if quality:
            log_message(
                f'INFO: sample accuracy={quality["accuracy"]:.4f} '
                f'n={int(quality["sample_size"])}'
            )
        else:
            log_message('WARN: predictions sample пустой (accuracy=None)')

        print(json.dumps(result, ensure_ascii=False, indent=2))
        if bucket:
            upload_results(bucket, f'metrics/throughput_{log_ts}.json', result, s3_cfg)
        return result
    except Exception:
        log_message(f'ERROR: {traceback.format_exc()}')
        raise
    finally:
        if bucket:
            upload_log_to_s3(bucket, f'logs/evaluate_{log_ts}.log', s3_cfg)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument('--bootstrap_servers', required=True)
    parser.add_argument('--input_topic', required=True)
    parser.add_argument('--output_topic', required=True)
    parser.add_argument('--group_id', default='spark-fraud-infer')
    parser.add_argument('--kafka_user', required=True)
    parser.add_argument('--kafka_password', required=True)
    parser.add_argument('--security_protocol', default='SASL_SSL')
    parser.add_argument('--sasl_mechanism', default='SCRAM-SHA-512')
    parser.add_argument('--ssl_cafile', default=DEFAULT_CA_PATH)
    parser.add_argument(
        '--rates',
        default='50,100,200,400',
        help='TPS ступени (для интерпретации уже собранной истории или одиночных замеров)',
    )
    parser.add_argument(
        '--measure_interval_sec',
        type=float,
        default=15.0,
        help='Интервал между замерами lag_before/lag_after на текущей нагрузке',
    )
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--lag_growth_delta', type=int, default=50)
    parser.add_argument('--bucket', default='')
    parser.add_argument('--s3_endpoint_url', default='https://storage.yandexcloud.net')
    parser.add_argument('--s3_access_key', default='')
    parser.add_argument('--s3_secret_key', default='')
    parser.add_argument('--assumed_rate', type=float, default=None)
    args = parser.parse_args()

    rates = [float(x) for x in args.rates.split(',') if x.strip()]
    execute_evaluation(
        bootstrap_servers=args.bootstrap_servers,
        input_topic=args.input_topic,
        output_topic=args.output_topic,
        kafka_user=args.kafka_user,
        kafka_password=args.kafka_password,
        rates=rates,
        group_id=args.group_id,
        security_protocol=args.security_protocol,
        sasl_mechanism=args.sasl_mechanism,
        ssl_cafile=args.ssl_cafile,
        measure_interval_sec=args.measure_interval_sec,
        rounds=args.rounds,
        lag_growth_delta=args.lag_growth_delta,
        assumed_rate=args.assumed_rate,
        bucket=args.bucket,
        s3_cfg={
            'endpoint_url': args.s3_endpoint_url,
            'access_key': args.s3_access_key,
            'secret_key': args.s3_secret_key,
        },
    )


if __name__ == '__main__':
    main()
