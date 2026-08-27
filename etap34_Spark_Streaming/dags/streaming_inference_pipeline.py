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
S3_SRC_BURL = join_path(create_bucket_scheme(S3_BUCKET_NAME), 'src')
S3_DP_LOGS_BUCKET = join_path(S3_BUCKET_NAME, 'airflow_logs')
S3_VENV_ARCHIVE_BURL = join_file(create_bucket_scheme(S3_BUCKET_NAME), 'venvs/venv.tar.gz')

DP_SA_ID = Variable.get('DP_SA_ID')

MLFLOW_TRACKING_URI = Variable.get('MLFLOW_TRACKING_URI')

KAFKA_BOOTSTRAP_SERVERS = Variable.get('KAFKA_BOOTSTRAP_SERVERS')
KAFKA_INPUT_TOPIC = Variable.get('KAFKA_INPUT_TOPIC')
KAFKA_OUTPUT_TOPIC = Variable.get('KAFKA_OUTPUT_TOPIC')
KAFKA_PRODUCER_USER = Variable.get('KAFKA_PRODUCER_USER')
KAFKA_PRODUCER_PASSWORD = Variable.get('KAFKA_PRODUCER_PASSWORD')
KAFKA_CONSUMER_USER = Variable.get('KAFKA_CONSUMER_USER')
KAFKA_CONSUMER_PASSWORD = Variable.get('KAFKA_CONSUMER_PASSWORD')
KAFKA_SECURITY_PROTOCOL = Variable.get('KAFKA_SECURITY_PROTOCOL', default_var='SASL_SSL')
KAFKA_SASL_MECHANISM = Variable.get('KAFKA_SASL_MECHANISM', default_var='SCRAM-SHA-512')

STREAM_DURATION_SEC = int(Variable.get('STREAM_DURATION_SEC', default_var='600'))
STEP_DURATION_SEC = int(Variable.get('STEP_DURATION_SEC', default_var='60'))
LOAD_RATES = Variable.get('LOAD_RATES', default_var='50,100,200,400')
PRODUCER_DELAY_SEC = int(Variable.get('PRODUCER_DELAY_SEC', default_var='45'))
SPARK_GROUP_ID = 'spark-fraud-infer'
DP_CLUSTER_ID = "{{ ti.xcom_pull(task_ids='dp-cluster-create-task') }}"

KAFKA_SPARK_PACKAGE = 'org.apache.spark:spark-sql-kafka-0-10_2.12:3.0.3'

VENV_PROPS = {
    'spark.submit.deployMode': 'cluster',
    'spark.yarn.dist.archives': f'{S3_VENV_ARCHIVE_BURL}#venv',
    'spark.yarn.appMasterEnv.PYSPARK_PYTHON': './venv/bin/python3',
    'spark.yarn.appMasterEnv.PYSPARK_DRIVER_PYTHON': './venv/bin/python3',
    'spark.executorEnv.PYSPARK_PYTHON': './venv/bin/python3',
    'spark.yarn.appMasterEnv.AWS_ACCESS_KEY_ID': S3_ACCESS_KEY,
    'spark.yarn.appMasterEnv.AWS_SECRET_ACCESS_KEY': S3_SECRET_KEY,
    'spark.yarn.appMasterEnv.MLFLOW_S3_ENDPOINT_URL': S3_ENDPOINT_URL,
    'spark.yarn.appMasterEnv.AWS_DEFAULT_REGION': 'ru-central1',
    'spark.executorEnv.AWS_ACCESS_KEY_ID': S3_ACCESS_KEY,
    'spark.executorEnv.AWS_SECRET_ACCESS_KEY': S3_SECRET_KEY,
    'spark.executorEnv.MLFLOW_S3_ENDPOINT_URL': S3_ENDPOINT_URL,
    'spark.executorEnv.AWS_DEFAULT_REGION': 'ru-central1',
}

with DAG(
    dag_id='streaming_inference_pipeline',
    start_date=datetime(year=2026, month=3, day=1),
    schedule=None,
    catchup=False,
    tags=['mlops', 'streaming', 'kafka', 'fraud'],
) as dag:
    create_spark_cluster = DataprocCreateClusterOperator(
        task_id='dp-cluster-create-task',
        folder_id=YC_FOLDER_ID,
        cluster_name=f'tmp-dp-stream-{uuid.uuid4()}',
        cluster_description='YC Spark Cluster for streaming inference',
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

    # Один job: streaming + producer thread + evaluate
    spark_streaming = DataprocCreatePysparkJobOperator(
        task_id='dp-spark-streaming-infer',
        cluster_id=DP_CLUSTER_ID,
        main_python_file_uri=join_file(S3_SRC_BURL, 'spark_streaming_infer.py'),
        connection_id=YC_SA_CONNECTION_ID,
        dag=dag,
        packages=[KAFKA_SPARK_PACKAGE],
        args=[
            '--bootstrap_servers', KAFKA_BOOTSTRAP_SERVERS,
            '--input_topic', KAFKA_INPUT_TOPIC,
            '--output_topic', KAFKA_OUTPUT_TOPIC,
            '--kafka_user', KAFKA_CONSUMER_USER,
            '--kafka_password', KAFKA_CONSUMER_PASSWORD,
            '--security_protocol', KAFKA_SECURITY_PROTOCOL,
            '--sasl_mechanism', KAFKA_SASL_MECHANISM,
            '--tracking_uri', MLFLOW_TRACKING_URI,
            '--duration_sec', str(STREAM_DURATION_SEC),
            '--group_id', SPARK_GROUP_ID,
            '--bucket', S3_BUCKET_NAME,
            '--s3_endpoint_url', S3_ENDPOINT_URL,
            '--s3_access_key', S3_ACCESS_KEY,
            '--s3_secret_key', S3_SECRET_KEY,
            '--run_producer', '1',
            '--producer_user', KAFKA_PRODUCER_USER,
            '--producer_password', KAFKA_PRODUCER_PASSWORD,
            '--producer_delay_sec', str(PRODUCER_DELAY_SEC),
            '--ramp', LOAD_RATES,
            '--step_duration', str(STEP_DURATION_SEC),
            '--data_prefix', 'cleaned_data',
            '--run_evaluate', '1',
            '--eval_rounds', '2',
            '--eval_measure_interval_sec', '10',
            '--lag_growth_delta', '50',
        ],
        properties={
            **VENV_PROPS,
            'spark.jars.packages': KAFKA_SPARK_PACKAGE,
        },
    )

    delete_spark_cluster = DataprocDeleteClusterOperator(
        task_id='dp-cluster-delete-task',
        cluster_id=DP_CLUSTER_ID,
        connection_id=YC_SA_CONNECTION_ID,
        trigger_rule=TriggerRule.ALL_DONE,
        dag=dag,
    )

    create_spark_cluster >> spark_streaming >> delete_spark_cluster
