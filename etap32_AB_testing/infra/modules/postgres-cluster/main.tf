resource "yandex_mdb_postgresql_cluster" "postgres_cluster" {
  name                = var.cluster_name
  environment         = "PRODUCTION"
  network_id          = var.network_id
  security_group_ids  = [var.security_group_id]
  deletion_protection = var.deletion_protection

  config {
    version = var.postgres_version
    resources {
      resource_preset_id = var.resource_preset_id
      disk_type_id       = var.disk_type_id
      disk_size          = var.disk_size
    }

    access {
      data_lens     = false
      web_sql       = true
      serverless    = false
      data_transfer = false
    }

    performance_diagnostics {
      enabled = true
      sessions_sampling_interval  = 60
      statements_sampling_interval = 600
    }

    pooler_config {
      pooling_mode = "TRANSACTION"
      pool_discard = true
    }
  }

  host {
    zone             = var.provider_config.zone
    subnet_id        = var.subnet_id
    assign_public_ip = var.assign_public_ip
  }

  maintenance_window {
    type = "WEEKLY"
    day  = "SAT"
    hour = 12
  }
}

resource "yandex_mdb_postgresql_database" "mlflow_db" {
  cluster_id = yandex_mdb_postgresql_cluster.postgres_cluster.id
  name       = var.postgres_db
  owner      = yandex_mdb_postgresql_user.mlflow_user.name
}

resource "yandex_mdb_postgresql_user" "mlflow_user" {
  cluster_id = yandex_mdb_postgresql_cluster.postgres_cluster.id
  name       = var.postgres_user
  password   = var.postgres_password

  settings = {
    default_transaction_isolation = "read committed"
    log_min_duration_statement    = 5000
  }

}