output "network_id" {
  description = "VPC network ID"
  value       = yandex_vpc_network.main.id
}

output "subnet_id" {
  description = "Subnet ID"
  value       = yandex_vpc_subnet.main.id
}

output "security_group_id" {
  description = "Security group ID"
  value       = yandex_vpc_security_group.k8s.id
}
