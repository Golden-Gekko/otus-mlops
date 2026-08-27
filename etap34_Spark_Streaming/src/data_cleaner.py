from argparse import ArgumentParser
from datetime import datetime, timezone
import os
from typing import Dict

import boto3
from botocore.exceptions import ClientError
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, mean, stddev, row_number
from pyspark.sql.window import Window


LOG_FILE_PATH = '/tmp/data_cleaner_job.log'


def to_boto3_name(path: str):
    return path.replace('s3://', '').replace('s3a://', '').strip('/')


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


def log_message(msg: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{timestamp}] {msg}'
    with open(LOG_FILE_PATH, 'a') as f:
        f.write(line + '\n')


def clean_data_pipeline(
    input_path: str, output_path: str, s3_cfg: Dict[str, str]
):
    log_message('INFO: Инициализация Spark сессии')

    try:
        builder = (
            SparkSession.builder
            .appName('CleanTransactionData')
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

        log_message('SUCSESS: Spark сессия успешно сконфигурирована')
    except Exception as e:
        log_message(f'ERROR: Ошибка создания Spark сессии: {str(e)}')
        raise

    spark = builder.getOrCreate()

    log_message(f'INFO: Загрузка данных из: {input_path}')
    df = (
        spark.read
        .option('header', 'false')
        .option('inferSchema', 'true')
        .option('comment', '#')
        .csv(input_path)
        .toDF(
            'transaction_id',
            'tx_datetime',
            'customer_id',
            'terminal_id',
            'tx_amount',
            'tx_time_seconds',
            'tx_time_days',
            'tx_fraud',
            'tx_fraud_scenario',
        )
    )

    initial_count = df.count()
    log_message(f'INFO: Исходное количество строк: {initial_count}')

    if initial_count == 0:
        log_message('ERROR: Входные данные пусты!')
        spark.stop()
        return

    df = df.dropna()
    df = df.dropDuplicates()
    df = df.withColumn(
        'rn',
        row_number().over(
            Window.partitionBy('transaction_id')
            .orderBy('tx_datetime')
        )
    ).filter(col('rn') == 1).drop('rn')

    df = df.filter(col('tx_amount') > 0)
    df = df.filter(col('customer_id') > 0)

    if df.count() > 0:
        stats = df.select(
            mean('tx_amount').alias('m'),
            stddev('tx_amount').alias('s')
        ).first()
        if stats and stats['s'] is not None and stats['s'] > 0:
            lower = stats['m'] - 3 * stats['s']
            upper = stats['m'] + 3 * stats['s']
            df = df.filter(
                (col('tx_amount') >= lower) & (col('tx_amount') <= upper)
            )

    final_count = df.count()
    log_message(f'INFO: Остаток данных: {final_count} строк '
                f'(удалено {1 - final_count / initial_count:.2%})')

    log_message(f'INFO: Сохранение результата в: {output_path}')
    df.write.mode('overwrite').parquet(output_path)
    spark.stop()
    log_message('SUCCESS: Обработка завершена успешно')


def main():
    try:
        parser = ArgumentParser()
        parser.add_argument('--input_data', required=True)
        parser.add_argument('--output_data', required=True)

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

        input_path = f'{args.input_data.strip("/")}/*.txt'
        output_path = args.output_data.strip()

        log_message(
            'INFO: Обработка бакета: '
            f"{to_boto3_name(logs_bucket).split('/')[0]}")
        clean_data_pipeline(
            input_path=input_path,
            output_path=output_path,
            s3_cfg=s3_cfg)

    except Exception as e:
        log_message(f'ERROR: КРИТИЧЕСКАЯ ОШИБКА: {e}')
    finally:
        try:
            job_time = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            log_s3_key = f'logs/cleaner_logs/data_cleaner-job-{job_time}.log'

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


if __name__ == '__main__':
    main()
