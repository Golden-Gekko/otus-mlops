variable "yc_token" {
  type        = string
  description = "YC OAuth token"
}

variable "yc_cloud_id" {
  type        = string
  description = "YC ID"
}

variable "yc_folder_id" {
  type        = string
  description = "YC Folder ID"
}

variable "yc_zone" {
  type        = string
  description = "Zone for YC resources"
  default     = "ru-central1-a"
}

variable "network_name" {
  type        = string
  description = "Name of the network"
  default     = "otus-network"
}

variable "subnet_name" {
  type        = string
  description = "Name of the subnet"
  default     = "otus-subnet"
}

variable "subnet_range" {
  type        = string
  description = "CIDR for subnet"
  default     = "10.0.0.0/24"
}

variable "route_table_name" {
  type        = string
  description = "Name of the route table"
  default     = "otus-route-table"
}

variable "nat_gateway_name" {
  type        = string
  description = "Name of the NAT gateway"
  default     = "otus-nat-gateway"
}

variable "security_group_name" {
  type        = string
  description = "Name of the security group"
  default     = "otus-security-group"
}

variable "service_account_name" {
  type        = string
  description = "Name of the service account"
  default     = "otus-sa"
}

variable "bucket_name" {
  type        = string
  description = "Base name for bucket"
  default     = "otus-bucket"
}

variable "dataproc_cluster_name" {
  type        = string
  description = "Name of the Dataproc cluster"
  default     = "otus-dataproc-cluster"
}

variable "dataproc_version" {
  type        = string
  description = "Dataproc version"
  default     = "2.0"
}

variable "public_key_path" {
  type        = string
  description = "Path to public SSH key"
}

variable "private_key_path" {
  type        = string
  description = "Path to private SSH key"
}

variable "dataproc_master" {
  type = object({
    resource_preset_id = string
    disk_type_id       = string
    disk_size          = number
  })
  default = {
    resource_preset_id = "s3-c2-m8"
    disk_type_id       = "network-ssd"
    disk_size          = 40
  }
  description = "Master-node config"
}

variable "dataproc_data" {
  type = object({
    resource_preset_id = string
    disk_type_id       = string
    disk_size          = number
    hosts_count        = number
  })
  default = {
    resource_preset_id = "s3-c4-m16"
    disk_type_id       = "network-ssd"
    disk_size          = 128
    hosts_count        = 3
  }
  description = "Data-node config"
}

variable "instance_name" {
  type        = string
  description = "VM name"
  default     = "otus-proxy-vm"
}

variable "image_id" {
  type        = string
  description = "ID Ubuntu image (20.04)"
  default     = "fd808e721rc1vt7jkd0o"
}