import uuid
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.settings import Session
from airflow.models import Connection, Variable
from airflow.utils.trigger_rule import TriggerRule
from airflow.providers.yandex.operators.dataproc import (
    DataprocCreateClusterOperator,
    DataprocCreatePysparkJobOperator,
    DataprocDeleteClusterOperator
)


def create_bucket_scheme(path: str, scheme: str = 's3a://') -> str:
    return (
        f"{scheme}"
        f"{path.replace('s3://', '').replace('s3a://', '').strip('/')}"
    )


def join_path(path: str, key: str) -> str:
    return f"{path.strip('/')}/{key.strip('/')}/"


def join_file(path: str, filename: str) -> str:
    return f"{path.strip('/')}/{filename.strip('/')}"


# Общие переменные для вашего облака
YC_ZONE = Variable.get('YC_ZONE')
YC_FOLDER_ID = Variable.get('YC_FOLDER_ID')
YC_SUBNET_ID = Variable.get('YC_SUBNET_ID')
YC_SSH_PUBLIC_KEY = Variable.get('YC_SSH_PUBLIC_KEY')

# Переменные для подключения к Object Storage
S3_ENDPOINT_URL = Variable.get('S3_ENDPOINT_URL')
S3_ACCESS_KEY = Variable.get('S3_ACCESS_KEY')
S3_SECRET_KEY = Variable.get('S3_SECRET_KEY')
S3_BUCKET_NAME = Variable.get('S3_BUCKET_NAME')
S3_INPUT_DATA_BURL = join_path(
    create_bucket_scheme(S3_BUCKET_NAME), 'input_data')
S3_TRAIN_DATA_BURL = join_path(
    create_bucket_scheme(S3_BUCKET_NAME), 'cleaned_data')
S3_OUTPUT_MODEL_BURL = join_path(
    create_bucket_scheme(S3_BUCKET_NAME), 'models')
S3_SRC_BURL = join_path(
    create_bucket_scheme(S3_BUCKET_NAME), 'src')
S3_DP_LOGS_BUCKET = join_path(S3_BUCKET_NAME, 'airflow_logs')
S3_VENV_ARCHIVE_BURL = join_file(
    create_bucket_scheme(S3_BUCKET_NAME), 'venvs/venv.tar.gz')

# Переменные необходимые для создания Dataproc кластера
DP_SA_AUTH_KEY_PUBLIC_KEY = Variable.get('DP_SA_AUTH_KEY_PUBLIC_KEY')
DP_SA_JSON = Variable.get('DP_SA_JSON')
DP_SA_ID = Variable.get('DP_SA_ID')
DP_SECURITY_GROUP_ID = Variable.get('DP_SECURITY_GROUP_ID')

# MLflow переменные
MLFLOW_TRACKING_URI = Variable.get('MLFLOW_TRACKING_URI')
MLFLOW_EXPERIMENT_NAME = 'fraud_detection'

# Создание подключения для Object Storage
YC_S3_CONNECTION = Connection(
    conn_id='yc-s3',
    conn_type='s3',
    host=S3_ENDPOINT_URL,
    extra={
        'aws_access_key_id': S3_ACCESS_KEY,
        'aws_secret_access_key': S3_SECRET_KEY,
        'host': S3_ENDPOINT_URL,
    },
)
# Создание подключения для Dataproc
YC_SA_CONNECTION = Connection(
    conn_id='yc-sa',
    conn_type='yandexcloud',
    extra={
        'extra__yandexcloud__public_ssh_key': DP_SA_AUTH_KEY_PUBLIC_KEY,
        'extra__yandexcloud__service_account_json': DP_SA_JSON,
    },
)


# Проверка наличия подключений в Airflow
def setup_airflow_connections(*connections: Connection) -> None:
    session = Session()
    try:
        for conn in connections:
            print('Checking connection:', conn.conn_id)
            if not session.query(Connection).filter(Connection.conn_id == conn.conn_id).first():
                session.add(conn)
                print('Added connection:', conn.conn_id)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


# Функция для выполнения setup_airflow_connections в рамках оператора
def run_setup_connections(**kwargs):
    setup_airflow_connections(YC_S3_CONNECTION, YC_SA_CONNECTION)
    return True


# Настройки DAG
with DAG(
    dag_id='training_baseline',
    start_date=datetime(year=2026, month=2, day=6),
    schedule_interval='@once',  # Одноразовый запуск
    catchup=False
) as dag:
    # 1 Создание подключений
    setup_connections = PythonOperator(
        task_id='setup_connections',
        python_callable=run_setup_connections,
    )

    # 2 Создание Dataproc клаcтера
    create_spark_cluster = DataprocCreateClusterOperator(
        task_id='dp-cluster-create-task',
        folder_id=YC_FOLDER_ID,
        cluster_name=f'tmp-dp-{uuid.uuid4()}',
        cluster_description='YC Spark Cluster',
        subnet_id=YC_SUBNET_ID,
        s3_bucket=S3_DP_LOGS_BUCKET,
        service_account_id=DP_SA_ID,
        ssh_public_keys=YC_SSH_PUBLIC_KEY,
        zone=YC_ZONE,
        cluster_image_version='2.0',

        # masternode
        masternode_resource_preset='s3-c2-m8',
        masternode_disk_type='network-ssd',
        masternode_disk_size=20,

        # datanodes
        datanode_resource_preset='s3-c4-m16',
        datanode_disk_type='network-ssd',
        datanode_disk_size=50,
        datanode_count=2,

        # computenodes
        computenode_count=0,

        # software
        services=['YARN', 'SPARK', 'HDFS', 'MAPREDUCE'],
        connection_id=YC_SA_CONNECTION.conn_id,
        dag=dag,
    )

    # 3 Запуск задания PySpark очистки данных
    poke_spark_processing = DataprocCreatePysparkJobOperator(
        task_id='dp-cluster-pyspark-clean-task',
        main_python_file_uri=join_file(S3_SRC_BURL, 'data_cleaner.py'),
        connection_id=YC_SA_CONNECTION.conn_id,
        dag=dag,
        args=[
            '--input_data', S3_INPUT_DATA_BURL,
            '--output_data', S3_TRAIN_DATA_BURL,
            '--bucket', S3_BUCKET_NAME,
            '--s3_endpoint_url', S3_ENDPOINT_URL,
            '--s3_access_key', S3_ACCESS_KEY,
            '--s3_secret_key', S3_SECRET_KEY,
        ],
    )

    # Запуск задания PySpark для обучения модели
    train_model = DataprocCreatePysparkJobOperator(
        task_id='dp-cluster-pyspark-train-task',
        main_python_file_uri=join_file(S3_SRC_BURL, 'baseline.py'),
        connection_id=YC_SA_CONNECTION.conn_id,
        dag=dag,
        args=[
            '--input_data', S3_TRAIN_DATA_BURL,
            '--output_model', join_path(
                S3_OUTPUT_MODEL_BURL,
                f"model_{datetime.now().strftime('%Y%m%d')}"
            ),
            '--tracking_uri', MLFLOW_TRACKING_URI,
            '--experiment_name', MLFLOW_EXPERIMENT_NAME,
            '--run_name', f"training_{datetime.now().strftime('%Y%m%d_%H%M')}",
            '--bucket', S3_BUCKET_NAME,
            '--s3_endpoint_url', S3_ENDPOINT_URL,
            '--s3_access_key', S3_ACCESS_KEY,
            '--s3_secret_key', S3_SECRET_KEY
        ],
        properties={
            'spark.submit.deployMode': 'cluster',
            'spark.yarn.dist.archives': f'{S3_VENV_ARCHIVE_BURL}#venv',
            'spark.yarn.appMasterEnv.PYSPARK_PYTHON': './venv/bin/python3',
            'spark.yarn.appMasterEnv.PYSPARK_DRIVER_PYTHON': './venv/bin/python3',
            'spark.executorEnv.PYSPARK_PYTHON': './venv/bin/python3',
        },
    )

    # 5 удаление Dataproc кластера
    delete_spark_cluster = DataprocDeleteClusterOperator(
        task_id='dp-cluster-delete-task',
        trigger_rule=TriggerRule.ALL_DONE,
        dag=dag,
    )

    # Формирование DAG из указанных выше этапов
    setup_connections >> create_spark_cluster >> poke_spark_processing >> train_model >> delete_spark_cluster
