import json
from pathlib import Path

import boto3


def upload_venv(variables_file='../infra/variables.json'):
    with open(variables_file, 'r', encoding='utf-8') as f:
        vars_data = json.load(f)

    bucket_name = vars_data['S3_BUCKET_NAME']
    s3 = boto3.client('s3', endpoint_url='https://storage.yandexcloud.net')

    archive_path = Path('venvs/venv.tar.gz')

    if not archive_path.exists():
        print(f'Архив не найден: {archive_path}')
        print(
            'Создайте архив "venvs/venv.tar.gz" с виртуальным окружением '
            '"requirements.txt"')
        return

    s3_key = 'venvs/venv.tar.gz'
    print(f'Загрузка {archive_path} -> s3://{bucket_name}/{s3_key}')

    try:
        s3.upload_file(str(archive_path), bucket_name, s3_key)
        print('Архив виртуального окружения загружен')
    except Exception as e:
        print(f'Ошибка загрузки: {e}')


if __name__ == '__main__':
    upload_venv()
