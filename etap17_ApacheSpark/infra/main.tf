# *** IAM-РЕСУРСЫ ***
# Сервисный аккаунт
resource "yandex_iam_service_account" "sa" {
  name        = var.service_account_name
  description = "Service account for Dataproc cluster and related services"
}

# Роли сервисного аккаунта
resource "yandex_resourcemanager_folder_iam_member" "sa_roles" {
  for_each = toset([
    "compute.admin",         # Управление виртуальными машинами
    "dataproc.agent",        # Необходимо для работы узлов кластера
    "dataproc.editor",       # Управление кластерами Data Proc
    "mdb.dataproc.agent",    # Дополнительные права для сервисов в кластере
    "storage.admin",         # Управление Object Storage
    "storage.editor",        # Полные права на управление объектами в бакетах
    "storage.uploader",      # Загрузка файлов в бакет
    "storage.viewer",        # Чтение содержимого бакета
    "vpc.user",              # Доступ к сетевым ресурсам (VPC, подсети)
    "vpc.admin",             # Управление сетевыми ресурсами
    "iam.serviceAccounts.user" # Возможность использовать сервисный аккаунт
  ])

  folder_id = var.yc_folder_id
  role      = each.key
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
}

# Access key для доступа к Object Storage по S3
resource "yandex_iam_service_account_static_access_key" "sa-static-key" {
  service_account_id = yandex_iam_service_account.sa.id
  description        = "Static access key for object storage"
}

# *** СЕТЕВЫЕ РЕСУРСЫ ***
# Виртуальная сеть
resource "yandex_vpc_network" "network" {
  name = var.network_name
}

# Шлюз NAT
resource "yandex_vpc_gateway" "nat_gateway" {
  name = var.nat_gateway_name
  shared_egress_gateway {}
}

# Таблица маршрутизации
resource "yandex_vpc_route_table" "route_table" {
  name       = var.route_table_name
  network_id = yandex_vpc_network.network.id

  static_route {
    destination_prefix = "0.0.0.0/0"
    gateway_id         = yandex_vpc_gateway.nat_gateway.id
  }
}

# Подсеть
resource "yandex_vpc_subnet" "subnet" {
  name           = var.subnet_name
  zone           = var.yc_zone
  network_id     = yandex_vpc_network.network.id
  v4_cidr_blocks = [var.subnet_range]
  route_table_id = yandex_vpc_route_table.route_table.id
}

# Правила сетевого доступа к виртуальным машинам
resource "yandex_vpc_security_group" "security_group" {
  name        = var.security_group_name
  description = "Security group for Dataproc cluster"
  network_id  = yandex_vpc_network.network.id

  # Входящий трафик от самих себя
  ingress {
    protocol          = "ANY"
    predefined_target = "self_security_group"
    description       = "Allow internal cluster communication (ingress)"
  }

  # Исходящий трафик к самим себе
  egress {
    protocol          = "ANY"
    predefined_target = "self_security_group"
    description       = "Allow internal cluster communication (egress)"
  }

  # Входящий SSH
  ingress {
    protocol       = "TCP"
    port           = 22
    v4_cidr_blocks = ["0.0.0.0/0"]
    description    = "SSH access"
  }

  # Входящий HTTPS
  ingress {
    protocol       = "TCP"
    port           = 443
    v4_cidr_blocks = ["0.0.0.0/0"]
    description    = "HTTPS UI"
  }

  # Входящий Jupyter
  ingress {
    protocol       = "TCP"
    port           = 8888
    v4_cidr_blocks = ["0.0.0.0/0"]
    description    = "Jupyter Notebook access"
  }

  # Весь исходящий трафик
  egress {
    protocol       = "ANY"
    v4_cidr_blocks = ["0.0.0.0/0"]
    description    = "Outbound to internet"
  }
}

# *** OBJECT STORAGE ***
# Бакет
resource "yandex_storage_bucket" "data_bucket" {
  bucket        = "${var.bucket_name}-${var.yc_folder_id}"
  access_key    = yandex_iam_service_account_static_access_key.sa-static-key.access_key
  secret_key    = yandex_iam_service_account_static_access_key.sa-static-key.secret_key
  force_destroy = true

  # Публичный на чтение
  anonymous_access_flags {
    read = true
    list = true
  }
}


# *** DATAPROC КЛАСТЕР ***
# Кластер
resource "yandex_dataproc_cluster" "dataproc_cluster" {
  depends_on         = [yandex_resourcemanager_folder_iam_member.sa_roles]

  bucket             = yandex_storage_bucket.data_bucket.bucket
  name               = var.dataproc_cluster_name
  description        = "Dataproc Cluster created by Terraform for OTUS hw"
  service_account_id = yandex_iam_service_account.sa.id
  zone_id            = var.yc_zone
  security_group_ids = [yandex_vpc_security_group.security_group.id]

  cluster_config {
    version_id = var.dataproc_version

    # Настройки Hadoop-стека
    hadoop {
      services = ["HDFS", "YARN", "SPARK", "HIVE", "TEZ"]
      ssh_public_keys = [file(var.public_key_path)]
    }

    # Мастер-узел
    subcluster_spec {
      name           = "master"
      role           = "MASTERNODE"
      hosts_count    = 1
      assign_public_ip = true
      subnet_id      = yandex_vpc_subnet.subnet.id
      resources {
        resource_preset_id = var.dataproc_master.resource_preset_id
        disk_type_id       = var.dataproc_master.disk_type_id
        disk_size          = var.dataproc_master.disk_size
      }
    }

    # Дата-ноды
    subcluster_spec {
      name        = "data"
      role        = "DATANODE"
      hosts_count = var.dataproc_data.hosts_count
      subnet_id   = yandex_vpc_subnet.subnet.id
      resources {
        resource_preset_id = var.dataproc_data.resource_preset_id
        disk_type_id       = var.dataproc_data.disk_type_id
        disk_size          = var.dataproc_data.disk_size
      }
    }
  }
}

# *** ВСПОМОГАТЕЛЬНАЯ ВМ ***

resource "yandex_compute_disk" "boot_disk" {
  name     = "boot-disk-proxy"
  zone     = var.yc_zone
  image_id = var.image_id
  size     = 30
}

resource "yandex_compute_instance" "proxy" {
  name                      = var.instance_name
  zone                      = var.yc_zone
  platform_id               = "standard-v3"
  service_account_id        = yandex_iam_service_account.sa.id
  allow_stopping_for_update = true

  metadata = {
    ssh-keys = "ubuntu:${file(var.public_key_path)}"
    user-data = templatefile("${path.root}/scripts/user_data.sh", {
      token        = var.yc_token
      cloud_id     = var.yc_cloud_id
      folder_id    = var.yc_folder_id
      private_key  = file(var.private_key_path)
      access_key   = yandex_iam_service_account_static_access_key.sa-static-key.access_key
      secret_key   = yandex_iam_service_account_static_access_key.sa-static-key.secret_key
      s3_bucket    = yandex_storage_bucket.data_bucket.bucket
      copy_limit   = var.s3_copy_limit
    })
  }

  scheduling_policy {
    preemptible = true
  }

  resources {
    cores  = 2
    memory = 16
  }

  boot_disk {
    disk_id = yandex_compute_disk.boot_disk.id
  }

  network_interface {
    subnet_id = yandex_vpc_subnet.subnet.id
    nat       = true
  }

  metadata_options {
    gce_http_endpoint = 1
    gce_http_token    = 1
  }

  connection {
    type        = "ssh"
    user        = "ubuntu"
    private_key = file(var.private_key_path)
    host        = self.network_interface[0].nat_ip_address
  }

  provisioner "remote-exec" {
    inline = [
      "sudo cloud-init status --wait",
      "echo 'User-data script log:' | sudo tee /var/log/user_data_final.log",
      "sudo cat /var/log/cloud-init-output.log | sudo tee -a /var/log/user_data_final.log"
    ]
  }

  depends_on = [yandex_dataproc_cluster.dataproc_cluster]
}