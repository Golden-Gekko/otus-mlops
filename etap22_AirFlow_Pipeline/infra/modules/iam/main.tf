# Сервисный аккаунт
resource "yandex_iam_service_account" "sa" {
  name        = var.service_account_name
  description = "Service account for Airflow management"
}

resource "yandex_resourcemanager_folder_iam_member" "sa_roles" {
  for_each = toset([
    "compute.admin",         # Управление виртуальными машинами
    "dataproc.agent",        # Необходимо для работы узлов кластера
    "dataproc.editor",       # Управление кластерами Data Proc
    "managed-airflow.admin", # Администратор AirFlow
    "managed-airflow.integrationProvider", # настройка внешних подключений к AirFlow
    "mdb.dataproc.agent",    # Дополнительные права для сервисов в кластере
    "storage.admin",         # Управление Object Storage
    "storage.editor",        # Полные права на управление объектами в бакетах
    "storage.uploader",      # Загрузка файлов в бакет
    "storage.viewer",        # Чтение содержимого бакета
    "vpc.user",              # Доступ к сетевым ресурсам (VPC, подсети)
    "vpc.admin",             # Управление сетевыми ресурсами
    "iam.serviceAccounts.user", # Возможность использовать сервисный аккаунт
    "logging.writer",        # Для записи логов
    "monitoring.editor"      # Для записи метрик
  ])

  folder_id = var.provider_config.folder_id
  role      = each.key
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
}

# Access key для доступа к Object Storage по S3
resource "yandex_iam_service_account_static_access_key" "sa_static_key" {
  service_account_id = yandex_iam_service_account.sa.id
  description        = "Static access key for service account"
}

# Сохранение Access key S3
resource "local_file" "sa_static_key_file" {
  content = jsonencode({
    id                 = yandex_iam_service_account_static_access_key.sa_static_key.id
    service_account_id = yandex_iam_service_account_static_access_key.sa_static_key.service_account_id
    created_at         = yandex_iam_service_account_static_access_key.sa_static_key.created_at
    s3_key_id          = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    s3_secret_key      = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
  })
  filename        = "${path.module}/static_key.json"
  file_permission = "0600"
}

# Ключ для аутентификации через JWT
resource "yandex_iam_service_account_key" "sa_auth_key" {
  service_account_id = yandex_iam_service_account.sa.id
}

# Сохранение JWT ключа
resource "local_file" "sa_auth_key_file" {
  content = jsonencode({
    id                  = yandex_iam_service_account_key.sa_auth_key.id
    service_account_id  = yandex_iam_service_account_key.sa_auth_key.service_account_id
    created_at          = yandex_iam_service_account_key.sa_auth_key.created_at
    public_key          = yandex_iam_service_account_key.sa_auth_key.public_key
    private_key         = regex("-----BEGIN PRIVATE KEY-----[\\s\\S]*$", yandex_iam_service_account_key.sa_auth_key.private_key)
  })
  filename        = "${path.module}/authorized_key.json"
  file_permission = "0600"
}
