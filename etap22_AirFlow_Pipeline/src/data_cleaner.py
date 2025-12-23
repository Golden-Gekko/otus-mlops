from argparse import ArgumentParser
from datetime import datetime, timezone
import os
import sys

import boto3
from botocore.exceptions import ClientError
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, mean, stddev, row_number
from pyspark.sql.window import Window


LOG_FILE_PATH = '/tmp/data_cleaner_job.log'
S3_CLIENT = None


def init_s3_client(endpoint_url, access_key, secret_key):
    global S3_CLIENT
    S3_CLIENT = boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def upload_log_to_s3(bucket: str, log_key: str):
    if not os.path.exists(LOG_FILE_PATH):
        return
    try:
        S3_CLIENT.upload_file(LOG_FILE_PATH, bucket, log_key)
        print(f'Лог успешно загружен в s3://{bucket}/{log_key}')
    except ClientError as e:
        print(f'Ошибка загрузки лога в S3: {e}')
    except Exception as e:
        print(f'Неожиданная ошибка при загрузке лога: {e}')


def log_message(msg: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{timestamp}] {msg}'
    with open(LOG_FILE_PATH, 'a') as f:
        f.write(line + '\n')


def clean_data_pipeline(input_path: str, output_path: str):
    log_message('Инициализация Spark сессии')
    spark = (
        SparkSession.builder
        .appName('clean-transaction-data')
        .getOrCreate()
    )

    log_message(f'Загрузка данных из: {input_path}')
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
    log_message(f'Исходное количество строк: {initial_count}')

    if initial_count == 0:
        log_message('Входные данные пусты!')
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
    log_message(f'Остаток данных: {final_count} строк '
                f'(удалено {1 - final_count / initial_count:.2%})')

    log_message(f'Сохранение результата в: {output_path}')
    df.write.mode('overwrite').parquet(output_path)
    spark.stop()
    log_message('Обработка завершена успешно')


def main():
    with open(LOG_FILE_PATH, 'w') as log_file:
        try:
            parser = ArgumentParser()
            parser.add_argument('--bucket', required=True)
            parser.add_argument('--s3-endpoint', required=True)
            parser.add_argument('--s3-access-key', required=True)
            parser.add_argument('--s3-secret-key', required=True)
            args = parser.parse_args()

            init_s3_client(
                endpoint_url=args.s3_endpoint,
                access_key=args.s3_access_key,
                secret_key=args.s3_secret_key
            )

            bucket_name = args.bucket.strip()
            input_path = f's3a://{bucket_name}/input_data/*.txt'
            output_path = f's3a://{bucket_name}/output_data/'

            log_message(f'Обработка бакета: {bucket_name}')
            clean_data_pipeline(input_path, output_path)

        except Exception as e:
            log_message(f'КРИТИЧЕСКАЯ ОШИБКА: {e}')
            sys.exit(1)
        finally:
            job_time = (
                datetime.now(timezone.utc)
                .replace(tzinfo=None)
                .strftime('%Y%m%d-%H%M%S')
            )
            log_s3_key = f'spark-logs/data_cleaner-job-{job_time}.log'
            upload_log_to_s3(args.bucket, log_s3_key)


if __name__ == '__main__':
    main()
