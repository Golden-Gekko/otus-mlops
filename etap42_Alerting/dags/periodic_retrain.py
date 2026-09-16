import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

# Параметры DAG
DAG_ID = 'periodic_retrain'
SCHEDULE_INTERVAL = '@daily'
START_DATE = datetime(2024, 1, 1)
RETRIES = 1
RETRY_DELAY = timedelta(minutes=5)

# Параметры Kubernetes пода
NAMESPACE = 'airflow'
IMAGE = 'ghcr.io/golden-gekko/otus-mlops-alerting:latest'
MLFLOW_TRACKING_URI = os.getenv('MLFLOW_TRACKING_URI', 'http://mlflow-server:5000')


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': START_DATE,
    'retries': RETRIES,
    'retry_delay': RETRY_DELAY,
}


def _build_env_vars(tracking_uri: str) -> dict:
    env = {'MLFLOW_TRACKING_URI': tracking_uri}
    for key in (
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY',
        'MLFLOW_S3_ENDPOINT_URL',
        'AWS_DEFAULT_REGION',
    ):
        if os.getenv(key):
            env[key] = os.getenv(key)
    return env

with DAG(
    dag_id=DAG_ID,
    default_args=default_args,
    description='Периодическое переобучение stub-модели с логированием метрик в MLflow',
    schedule_interval=SCHEDULE_INTERVAL,
    catchup=False,
    tags=['mlops', 'retrain', 'fraud'],
) as dag:

    retrain_task = KubernetesPodOperator(
        task_id='retrain_model',
        name='retrain-model',
        namespace=NAMESPACE,
        image=IMAGE,
        cmds=['/app/.venv/bin/python', 'scripts/train_stub.py'],
        arguments=[
            '--rows', '5000',
            '--tracking-uri', MLFLOW_TRACKING_URI,
            '--model-name', 'fraud_detection_rf',
            '--alias', 'champion',
        ],
        env_vars=_build_env_vars(MLFLOW_TRACKING_URI),
        get_logs=True,
        log_events_on_failure=True,
        in_cluster=True,
        is_delete_operator_pod=True,
    )

    retrain_task
