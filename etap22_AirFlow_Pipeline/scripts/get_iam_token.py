import json
import time

import jwt
import requests


def get_iam_token(variables_file='../infra/variables.json'):
    with open(variables_file, 'r', encoding='utf-8') as f:
        vars_data = json.load(f)

    sa_json = json.loads(vars_data['DP_SA_JSON'])
    private_key = sa_json['private_key']
    key_id = sa_json['id']
    service_account_id = sa_json['service_account_id']

    now = int(time.time())
    payload = {
        'aud': 'https://iam.api.cloud.yandex.net/iam/v1/tokens',
        'iss': service_account_id,
        'iat': now,
        'exp': now + 600,  # 10 минут
    }

    encoded_jwt = jwt.encode(
        payload,
        private_key,
        algorithm='PS256',
        headers={'kid': key_id}
    )

    # Обмен JWT на IAM-токен
    resp = requests.post(
        'https://iam.api.cloud.yandex.net/iam/v1/tokens',
        json={'jwt': encoded_jwt}
    )
    resp.raise_for_status()
    return resp.json()['iamToken']
