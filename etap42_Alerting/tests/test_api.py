import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import PredictionOutput


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    response = client.get('/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'healthy'
    assert data['model_loaded'] is False


def test_ready_success(client, monkeypatch):
    class FakeManager:
        def load_model(self):
            pass

    monkeypatch.setattr(app.state, 'model_manager', FakeManager())
    response = client.get('/ready')
    assert response.status_code == 200
    assert response.json()['status'] == 'ready'


def test_ready_failure(client, monkeypatch):
    class FakeManager:
        def load_model(self):
            raise RuntimeError('model not found')

    monkeypatch.setattr(app.state, 'model_manager', FakeManager())
    response = client.get('/ready')
    assert response.status_code == 503
    assert 'model not found' in response.json()['detail']


def test_metrics(client):
    response = client.get('/metrics')
    assert response.status_code == 200
    assert 'predict_requests_total' in response.text


def test_predict_success(client, monkeypatch):
    class FakeManager:
        def predict(self, transactions):
            return [
                PredictionOutput(transaction_id=1, prediction=0, probability=0.123456),
                PredictionOutput(transaction_id=2, prediction=1, probability=0.876544),
            ]

    monkeypatch.setattr(app.state, 'model_manager', FakeManager())
    payload = {
        'transactions': [
            {
                'transaction_id': 1,
                'tx_datetime': '2024-01-15 10:30:00',
                'customer_id': 123,
                'terminal_id': 456,
                'tx_amount': 100.5,
                'tx_time_seconds': 1000,
                'tx_time_days': 1,
            },
            {
                'transaction_id': 2,
                'tx_datetime': '2024-01-16 12:00:00',
                'customer_id': 124,
                'terminal_id': 457,
                'tx_amount': 5000.0,
                'tx_time_seconds': 2000,
                'tx_time_days': 2,
            },
        ]
    }
    response = client.post('/predict', json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data['predictions']) == 2
    assert data['predictions'][0]['transaction_id'] == 1
    assert data['predictions'][0]['prediction'] == 0
    assert 'probability' in data['predictions'][0]

    metrics_response = client.get('/metrics')
    assert 'predict_requests_total 1.0' in metrics_response.text


def test_predict_empty(client):
    response = client.post('/predict', json={'transactions': []})
    assert response.status_code == 422


def test_predict_invalid_payload(client):
    response = client.post('/predict', json={'transactions': [{'transaction_id': 'abc'}]})
    assert response.status_code == 422
