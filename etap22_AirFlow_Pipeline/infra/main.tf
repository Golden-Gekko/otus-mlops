module "iam" {
  source               = "./modules/iam"
  service_account_name = var.yc_service_account_name
  provider_config      = var.yc_config
}

module "network" {
  source          = "./modules/network"
  network_name    = var.yc_network_name
  subnet_name     = var.yc_subnet_name
  provider_config = var.yc_config
}

module "storage" {
  source          = "./modules/storage"
  bucket_name     = var.yc_bucket_name
  provider_config = var.yc_config
  access_key      = module.iam.access_key
  secret_key      = module.iam.secret_key

  depends_on = [module.iam]
}

module "airflow-cluster" {
  source             = "./modules/airflow-cluster"
  instance_name      = var.yc_instance_name
  subnet_id          = module.network.subnet_id
  service_account_id = module.iam.service_account_id
  admin_password     = var.admin_password
  bucket_name        = module.storage.bucket
  provider_config    = var.yc_config

  depends_on = [module.storage]
}

resource "local_file" "variables_file" {
  content = jsonencode({
    # общие переменные
    YC_ZONE           = var.yc_config.zone
    YC_FOLDER_ID      = var.yc_config.folder_id
    YC_SUBNET_ID      = module.network.subnet_id
    YC_SSH_PUBLIC_KEY = trimspace(file(var.public_key_path))
    # S3
    S3_ENDPOINT_URL = var.yc_storage_endpoint_url
    S3_ACCESS_KEY   = module.iam.access_key
    S3_SECRET_KEY   = module.iam.secret_key
    S3_BUCKET_NAME  = module.storage.bucket
    # Data Proc
    DP_SECURITY_GROUP_ID      = module.network.security_group_id
    DP_SA_ID                  = module.iam.service_account_id
    DP_SA_AUTH_KEY_PUBLIC_KEY = module.iam.public_key
    DP_SA_JSON = jsonencode({
      id                 = module.iam.auth_key_id
      service_account_id = module.iam.service_account_id
      created_at         = module.iam.auth_key_created_at
      public_key         = module.iam.public_key
      private_key        = module.iam.private_key
    })
    # Airflow
    AIRFLOW_ID              = module.airflow-cluster.airflow_id
    AIRFLOW_ADMIN_PASSWORD  = var.admin_password
  })
  filename        = "./variables.json"
  file_permission = "0600"
}
