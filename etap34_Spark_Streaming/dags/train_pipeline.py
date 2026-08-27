from datetime import datetime
import uuid

from airflow import DAG
from airflow.models import Variable
from airflow.providers.yandex.operators.dataproc import (
    DataprocCreateClusterOperator,
    DataprocCreatePysparkJobOperator,
    DataprocDeleteClusterOperator,
)
from airflow.task.trigger_rule import TriggerRule

YC_SA_CONNECTION_ID = 'yc-sa'


def create_bucket_scheme(path: str, scheme: str = 's3a://') -> str:
    return (
        f"{scheme}"
        f"{path.replace('s3://', '').replace('s3a://', '').strip('/')}"
    )


def join_path(path: str, key: str) -> str:
    return f"{path.strip('/')}/{key.strip('/')}/"


def join_file(path: str, filename: str) -> str:
    return f"{path.strip('/')}/{filename.strip('/')}"


YC_ZONE = Variable.get('YC_ZONE')
YC_FOLDER_ID = Variable.get('YC_FOLDER_ID')
YC_SUBNET_ID = Variable.get('YC_SUBNET_ID')
YC_SSH_PUBLIC_KEY = Variable.get('YC_SSH_PUBLIC_KEY')

S3_ENDPOINT_URL = Variable.get('S3_ENDPOINT_URL')
S3_ACCESS_KEY = Variable.get('S3_ACCESS_KEY')
S3_SECRET_KEY = Variable.get('S3_SECRET_KEY')
S3_BUCKET_NAME = Variable.get('S3_BUCKET_NAME')
S3_INPUT_DATA_BURL = join_path(create_bucket_scheme(S3_BUCKET_NAME), 'input_data')
S3_TRAIN_DATA_BURL = join_path(create_bucket_scheme(S3_BUCKET_NAME), 'cleaned_data')
S3_OUTPUT_MODEL_BURL = join_path(create_bucket_scheme(S3_BUCKET_NAME), 'models')
S3_SRC_BURL = join_path(create_bucket_scheme(S3_BUCKET_NAME), 'src')
S3_DP_LOGS_BUCKET = join_path(S3_BUCKET_NAME, 'airflow_logs')
S3_VENV_ARCHIVE_BURL = join_file(create_bucket_scheme(S3_BUCKET_NAME), 'venvs/venv.tar.gz')

DP_SA_ID = Variable.get('DP_SA_ID')

MLFLOW_TRACKING_URI = Variable.get('MLFLOW_TRACKING_URI')
MLFLOW_EXPERIMENT_NAME = 'fraud_detection'
DP_CLUSTER_ID = "{{ ti.xcom_pull(task_ids='dp-cluster-create-task') }}"

with DAG(
    dag_id='train_pipeline',
    start_date=datetime(year=2026, month=3, day=1),
    schedule=None,
    catchup=False,
    tags=['mlops', 'train', 'fraud'],
) as dag:
    create_spark_cluster = DataprocCreateClusterOperator(
        task_id='dp-cluster-create-task',
        folder_id=YC_FOLDER_ID,
        cluster_name=f'tmp-dp-train-{uuid.uuid4()}',
        cluster_description='YC Spark Cluster for training',
        subnet_id=YC_SUBNET_ID,
        s3_bucket=S3_DP_LOGS_BUCKET,
        service_account_id=DP_SA_ID,
        ssh_public_keys=YC_SSH_PUBLIC_KEY,
        zone=YC_ZONE,
        cluster_image_version='2.0',
        masternode_resource_preset='s3-c2-m8',
        masternode_disk_type='network-ssd',
        masternode_disk_size=20,
        datanode_resource_preset='s3-c4-m16',
        datanode_disk_type='network-ssd',
        datanode_disk_size=50,
        datanode_count=2,
        computenode_count=0,
        services=['YARN', 'SPARK', 'HDFS', 'MAPREDUCE'],
        connection_id=YC_SA_CONNECTION_ID,
        dag=dag,
    )

    clean_data = DataprocCreatePysparkJobOperator(
        task_id='dp-cluster-pyspark-clean-task',
        cluster_id=DP_CLUSTER_ID,
        main_python_file_uri=join_file(S3_SRC_BURL, 'data_cleaner.py'),
        connection_id=YC_SA_CONNECTION_ID,
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

    train_model = DataprocCreatePysparkJobOperator(
        task_id='dp-cluster-pyspark-train-task',
        cluster_id=DP_CLUSTER_ID,
        main_python_file_uri=join_file(S3_SRC_BURL, 'train.py'),
        connection_id=YC_SA_CONNECTION_ID,
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
            '--s3_secret_key', S3_SECRET_KEY,
        ],
        properties={
            'spark.submit.deployMode': 'cluster',
            'spark.yarn.dist.archives': f'{S3_VENV_ARCHIVE_BURL}#venv',
            'spark.yarn.appMasterEnv.PYSPARK_PYTHON': './venv/bin/python3',
            'spark.yarn.appMasterEnv.PYSPARK_DRIVER_PYTHON': './venv/bin/python3',
            'spark.executorEnv.PYSPARK_PYTHON': './venv/bin/python3',
        },
    )

    delete_spark_cluster = DataprocDeleteClusterOperator(
        task_id='dp-cluster-delete-task',
        cluster_id=DP_CLUSTER_ID,
        connection_id=YC_SA_CONNECTION_ID,
        trigger_rule=TriggerRule.ALL_DONE,
        dag=dag,
    )

    create_spark_cluster >> clean_data >> train_model >> delete_spark_cluster
