output "cluster_id" {
  description = "ID of the created Kubernetes cluster"
  value       = module.k8s.cluster_id
}

output "cluster_name" {
  description = "Name of the created Kubernetes cluster"
  value       = module.k8s.cluster_name
}

output "node_group_id" {
  description = "ID of the created node group"
  value       = module.k8s.node_group_id
}

output "external_v4_endpoint" {
  description = "External Kubernetes API endpoint"
  value       = module.k8s.external_v4_endpoint
}

output "subnet_id" {
  description = "ID of the created subnet"
  value       = module.network.subnet_id
}
