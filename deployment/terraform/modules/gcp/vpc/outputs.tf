output "network_id" {
  description = "ID of the VPC network, in the form projects/<project>/global/networks/<name>"
  value       = google_compute_network.this.id
}

output "network_name" {
  description = "Name of the VPC network"
  value       = google_compute_network.this.name
}

output "network_self_link" {
  description = "Self link of the VPC network"
  value       = google_compute_network.this.self_link
}

output "subnet_id" {
  description = "ID of the subnet"
  value       = google_compute_subnetwork.this.id
}

output "subnet_name" {
  description = "Name of the subnet"
  value       = google_compute_subnetwork.this.name
}

output "subnet_self_link" {
  description = "Self link of the subnet"
  value       = google_compute_subnetwork.this.self_link
}

output "pods_range_name" {
  description = "Name of the subnet's secondary range for GKE pods"
  value       = local.pods_range_name
}

output "services_range_name" {
  description = "Name of the subnet's secondary range for GKE services"
  value       = local.services_range_name
}

output "router_name" {
  description = "Name of the Cloud Router that carries the NAT"
  value       = google_compute_router.this.name
}

output "nat_name" {
  description = "Name of the Cloud NAT gateway"
  value       = google_compute_router_nat.this.name
}

# Cloud SQL and Memorystore fail to create on a network that has no Private
# Service Access peering yet, and nothing else orders them after it: both
# depend on the network, the peering depends on the network, so Terraform is
# free to run them together. Making this id arrive only once the peering exists
# serialises them for every consumer, rather than asking each one to remember a
# depends_on.
output "private_service_access_network_id" {
  description = "Network ID, available once the Private Service Access peering exists. Pass this, not network_id, to Cloud SQL and Memorystore."
  value       = google_compute_network.this.id

  depends_on = [google_service_networking_connection.this]
}
