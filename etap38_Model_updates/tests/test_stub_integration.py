import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent

if shutil.which('java') is None:
    pytest.skip('Java недоступна, интеграционный тест пропущен', allow_module_level=True)


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp('stub')
    mlruns = root / 'mlruns'
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / 'scripts' / 'train_stub.py'),
            '--rows',
            '300',
            '--tracking-uri',
            str(mlruns),
            '--output',
            str(root / 'models' / 'stub'),
            '--seed',
            '7',
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )
    os.environ['MLFLOW_TRACKING_URI'] = mlruns.resolve().as_uri()

    from app.main import app

    with TestClient(app) as c:
        yield c

    os.environ.pop('MLFLOW_TRACKING_URI', None)


def test_health_before_load(client):
    response = client.get('/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'healthy'
    assert data['model_loaded'] is False
    assert data['model_name'] == 'fraud_detection_rf'


def test_ready_loads_stub(client):
    response = client.get('/ready')
    assert response.status_code == 200
    assert response.json()['status'] == 'ready'
    assert client.get('/health').json()['model_loaded'] is True


def test_predict_with_stub(client):
    payload = {
        'transactions': [
            {
                'transaction_id': 1,
                'tx_datetime': '2024-01-15 10:30:00',
                'customer_id': 123,
                'terminal_id': 456,
                'tx_amount': 9000.0,
                'tx_time_seconds': 1000,
                'tx_time_days': 1,
            },
            {
                'transaction_id': 2,
                'tx_datetime': '2024-01-16 12:00:00',
                'customer_id': 124,
                'terminal_id': 457,
                'tx_amount': 10.0,
                'tx_time_seconds': 2000,
                'tx_time_days': 2,
            },
        ]
    }
    response = client.post('/predict', json=payload)
    assert response.status_code == 200
    predictions = response.json()['predictions']
    assert len(predictions) == 2
    for item in predictions:
        assert item['prediction'] in (0, 1)
        assert 0.0 <= item['probability'] <= 1.0
