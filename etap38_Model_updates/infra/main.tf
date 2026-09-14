module "network" {
  source = "./modules/network"

  folder_id    = var.yc_config.folder_id
  zone         = var.yc_config.zone
  network_cidr = var.network_cidr
}

module "k8s" {
  source = "./modules/k8s"

  folder_id          = var.yc_config.folder_id
  zone               = var.yc_config.zone
  cluster_name       = var.cluster_name
  node_count         = var.node_count
  node_preset        = var.node_preset
  node_disk_size     = var.node_disk_size
  network_id         = module.network.network_id
  subnet_id          = module.network.subnet_id
  security_group_ids = [module.network.security_group_id]
}
