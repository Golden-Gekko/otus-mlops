# Проекты в рамках курса [MLOps от OTUS](https://otus.ru/lessons/ml-bigdata/)


3. В Airflow UI (id из variables.json → AIRFLOW_ID):

Запусти train_pipeline → дождись success
В MLflow проверь модель fraud_detection_rf с @champion
Запусти streaming_inference_pipeline → success
4. Результат задания

DAG success в Airflow
Champion в MLflow Registry
Топики Kafka inputs / predictions
В бакете: metrics/ramp_*.json — там порог TPS, когда растёт очередь
5. Снести (чтобы не платить):

aws s3 rm s3://<BUCKET_NAME> --recursive --endpoint-url https://storage.yandexcloud.net
cd ../infra
terraform destroy