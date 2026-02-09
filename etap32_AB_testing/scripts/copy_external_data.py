import json

import boto3
from botocore.config import Config
from tqdm import tqdm


def copy_external_data(
        copy_limit='latest',
        variables_file='../infra/variables.json'):
    with open(variables_file, 'r', encoding='utf-8') as f:
        vars_data = json.load(f)

    bucket_name = vars_data['S3_BUCKET_NAME']
    src_bucket = 'otus-mlops-source-data'

    s3 = boto3.client(
        's3',
        endpoint_url='https://storage.yandexcloud.net',
        config=Config(
            connect_timeout=30,
            read_timeout=1000
        )
    )

    # Список файлов
    paginator = s3.get_paginator('list_objects_v2')
    files = []
    for page in paginator.paginate(Bucket=src_bucket):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                if key.endswith('.txt'):
                    files.append(key)

    if not files:
        print('Нет .txt файлов в источнике')
        return

    files.sort()
    if copy_limit == 'all':
        to_copy = files
    elif copy_limit == 'latest':
        to_copy = [files[-1]]
    elif copy_limit.isdigit():
        n = min(int(copy_limit), len(files))
        to_copy = files[:n]
    else:
        raise ValueError(f'Неверный copy_limit: {copy_limit}')

    pbar = tqdm(to_copy, desc='Копирование файлов')
    for key in pbar:
        pbar.set_postfix(file=key)
        dest_key = f"input_data/{key.split('/')[-1]}"
        s3.copy_object(
            CopySource={'Bucket': src_bucket, 'Key': key},
            Bucket=bucket_name,
            Key=dest_key,
            ACL='public-read'
        )

    print('Данные скопированы')
