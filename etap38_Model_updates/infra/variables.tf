variable "yc_config" {
  description = "Yandex Cloud configuration"
  type = object({
    token     = string
    cloud_id  = string
    folder_id = string
    zone      = string
  })
  sensitive = true
}

variable "cluster_name" {
  description = "Kubernetes cluster name"
  type        = string
  default     = "fraud-api-k8s"
}

variable "node_count" {
  description = "Number of worker nodes"
  type        = number
  default     = 3
}

variable "node_preset" {
  description = "Resource preset for worker nodes"
  type        = string
  default     = "s3-c4-m16"
}

variable "node_disk_size" {
  description = "Disk size for worker nodes in GB"
  type        = number
  default     = 50
}

variable "network_cidr" {
  description = "CIDR for the Kubernetes cluster network"
  type        = string
  default     = "10.200.0.0/16"
}
