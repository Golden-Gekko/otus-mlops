resource "yandex_airflow_cluster" "airflow_cluster" {
  name               = var.instance_name
  subnet_ids         = [var.subnet_id]
  service_account_id = var.service_account_id
  admin_password     = var.admin_password

  # Настройка синхронизации кода через S3‑хранилище
  code_sync = {
    s3 = {
      bucket = var.bucket_name
    }
  }

  # Конфигурация веб‑сервера Airflow (UI)
  webserver = {
    count              = 1
    resource_preset_id = "c1-m4"
  }

  # Конфигурация планировщика Airflow
  scheduler = {
    count              = 1
    resource_preset_id = "c1-m4"
  }

  # Конфигурация воркеров
  worker = {
    min_count          = 1
    max_count          = 2
    resource_preset_id = "c1-m4"
  }

  # Дополнительные настройки Airflow через airflow.cfg
  airflow_config = {
    # Настройки API Airflow
    "api" = {
      # Два метода аутентификации: базовая и через сессии
      "auth_backends" = "airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session"
    }
    # Настройки планировщика
    "scheduler" = {
      # Интервал (в секундах) между проверками директории с DAG на изменения
      "dag_dir_list_interval" = "10"
    }
  }

  # Настройка логирования кластера
  logging = {
    enabled   = true
    folder_id = var.provider_config.folder_id
    min_level = "INFO"
  }
}
