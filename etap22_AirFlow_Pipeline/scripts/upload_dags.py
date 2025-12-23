import json
from pathlib import Path

import boto3


def upload_dags(variables_file='../infra/variables.json'):
    with open(variables_file, 'r', encoding='utf-8') as f:
        vars_data = json.load(f)

    bucket_name = vars_data['S3_BUCKET_NAME']

    s3 = boto3.client(
        's3',
        endpoint_url='https://storage.yandexcloud.net'
    )

    dags_dir = Path('../dags')
    if not dags_dir.exists():
        print('Папка ../dags не найдена')
        return

    for dag_file in dags_dir.rglob('*.py'):
        key = f'dags/{dag_file.relative_to(dags_dir)}'
        print(f'Загрузка {key}')
        s3.upload_file(str(dag_file), bucket_name, key)

    print('DAG-файлы загружены')
