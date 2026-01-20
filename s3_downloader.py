import boto3
from botocore.config import Config

BUCKET_NAME = 'otus-mlops-source-data'
LOCAL_PATH = './downloaded_file.txt'


def connect_to_s3(endpoint_url='https://storage.yandexcloud.net'):
    return boto3.client(
        's3',
        endpoint_url=endpoint_url,
        config=Config(
            connect_timeout=30,
            read_timeout=1000
        )
    )


def list_files_from_s3(
    s3_client,
    bucket_name,
    extension='.txt',
):
    print(f'Получение списка файлов из бакета "{bucket_name}"...')
    paginator = s3_client.get_paginator('list_objects_v2')
    files = []
    for page in paginator.paginate(Bucket=bucket_name):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                if extension and key.endswith(extension):
                    files.append(key)

    if not files:
        print(f'В бакете "{bucket_name}" нет файлов "{extension}"')
        return
    print(*files, sep='\n')


def download_file_from_s3(
    s3_client,
    bucket_name,
    download_filename,
    local_path
):
    s3_client.download_file(bucket_name, download_filename, local_path)


if __name__ == '__main__':
    s3_client = connect_to_s3()
    # list_files_from_s3(s3_client, BUCKET_NAME)
    download_file_from_s3(
        s3_client=s3_client,
        bucket_name=BUCKET_NAME,
        download_filename='2019-08-22.txt',
        local_path=LOCAL_PATH
    )
