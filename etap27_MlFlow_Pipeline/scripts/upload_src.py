import json
from pathlib import Path

import boto3


def upload_src(variables_file='../infra/variables.json'):
    with open(variables_file, 'r', encoding='utf-8') as f:
        vars_data = json.load(f)

    bucket_name = vars_data['S3_BUCKET_NAME']
    s3 = boto3.client('s3', endpoint_url='https://storage.yandexcloud.net')

    src_dir = Path('../src')
    if not src_dir.exists():
        print('Папка ../src не найдена')
        return

    for src_file in src_dir.rglob('*'):
        if src_file.is_file():
            key = f'src/{src_file.relative_to(src_dir)}'
            print(f'Загрузка {key}')
            s3.upload_file(str(src_file), bucket_name, key)

    print('Исходный код загружен')
