variable "yc_instance_user" {
  type = string
}

variable "yc_instance_name" {
  type = string
}

variable "yc_network_name" {
  type = string
}

variable "yc_subnet_name" {
  type = string
}

variable "yc_service_account_name" {
  type = string
}

variable "yc_bucket_name" {
  type = string
}

variable "yc_storage_endpoint_url" {
  type    = string
  default = "https://storage.yandexcloud.net"
}

variable "ubuntu_image_family" {
  type    = string
}

variable "public_key_path" {
  type = string
}

variable "private_key_path" {
  type = string
}

variable "admin_password" {
  type        = string
  description = "Admin password for the Airflow web interface"
}

variable "yc_config" {
  type = object({
    token     = string
    cloud_id  = string
    folder_id = string
    zone      = string
  })
  description = "Yandex Cloud configuration"
}

variable "yc_mlflow_instance_name" {
  type = string
  description = "Name of the MLflow server instance"
}

variable "yc_postgres_cluster_name" {
  type = string
  description = "Name of the PostgreSQL cluster"
}

variable "postgres_password" {
  type        = string
  description = "Password for PostgreSQL database used by MLflow"
  sensitive   = true
}

variable "yc_kafka_cluster_name" {
  type        = string
  description = "Name of the Managed Kafka cluster"
}

variable "kafka_producer_password" {
  type        = string
  description = "Password for Kafka producer user"
  sensitive   = true
}

variable "kafka_consumer_password" {
  type        = string
  description = "Password for Kafka consumer user"
  sensitive   = true
}
