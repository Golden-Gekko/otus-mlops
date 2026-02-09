import json
import time

import requests

from get_iam_token import get_iam_token


def upload_airflow_variables(variables_file='../infra/variables.json'):
    with open(variables_file, 'r', encoding='utf-8') as f:
        vars_data = json.load(f)

    airflow_id = vars_data['AIRFLOW_ID']
    airflow_url = f'https://{airflow_id}.airflow.yandexcloud.net'

    iam_token = get_iam_token(variables_file)
    headers = {
        'Authorization': f'Bearer {iam_token}',
        'Content-Type': 'application/json'
    }

    # Проверка доступа
    resp = requests.get(f'{airflow_url}/api/v1/variables', headers=headers)
    resp.raise_for_status()
    print('Airflow API доступен')

    # Плоский словарь (DP_SA_JSON как JSON-строка)
    flat_vars = {}
    for k, v in vars_data.items():
        if k == 'DP_SA_JSON':
            flat_vars[k] = json.dumps(json.loads(v), separators=(',', ':'))
        else:
            flat_vars[k] = str(v)

    # Загрузка переменных
    for key, value in flat_vars.items():
        time.sleep(0.5)
        body = {'key': key, 'value': value}
        # Проверяем существование
        check_resp = requests.get(
            f'{airflow_url}/api/v1/variables/{key}', headers=headers)
        if check_resp.status_code == 200:
            method = 'PATCH'
            url = f'{airflow_url}/api/v1/variables/{key}'
        else:
            method = 'POST'
            url = f'{airflow_url}/api/v1/variables'
        time.sleep(0.5)
        resp = requests.request(method, url, json=body, headers=headers)
        # print(f'Ответ для "{key}": {resp.status_code} - {resp.text}')
        if resp.status_code in (200, 201):
            print(f'Переменная "{key}" загружета')
        else:
            print(f'Ошибка загрузки переменной "{key}": {resp.text}')
