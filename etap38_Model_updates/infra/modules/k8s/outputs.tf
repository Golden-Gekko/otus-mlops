output "cluster_id" {
  description = "Kubernetes cluster ID"
  value       = yandex_kubernetes_cluster.main.id
}

output "cluster_name" {
  description = "Kubernetes cluster name"
  value       = yandex_kubernetes_cluster.main.name
}

output "node_group_id" {
  description = "Node group ID"
  value       = yandex_kubernetes_node_group.main.id
}

output "external_v4_endpoint" {
  description = "External Kubernetes API endpoint"
  value       = yandex_kubernetes_cluster.main.master[0].external_v4_endpoint
}
