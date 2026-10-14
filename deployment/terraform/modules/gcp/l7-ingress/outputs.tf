output "ip_address" {
  description = "IPv4 address of the load balancer. Point the A record of each domain at it."
  value       = google_compute_global_address.this.address
}

output "address_name" {
  description = "Name of the address. Put it in the Gateway's spec.addresses as a NamedAddress."
  value       = google_compute_global_address.this.name
}

output "certificate_map_name" {
  description = "Name of the certificate map. Put it in the Gateway annotation networking.gke.io/certmap."
  value       = google_certificate_manager_certificate_map.this.name
}

output "dns_authorization_records" {
  description = "Record to add at the DNS provider for each domain, as { name, type, data }. Google issues a certificate only after its record resolves."
  value = {
    for d, a in google_certificate_manager_dns_authorization.this : d => {
      name = a.dns_resource_record[0].name
      type = a.dns_resource_record[0].type
      data = a.dns_resource_record[0].data
    }
  }
}

output "certificate_ids" {
  description = "ID of the Google-managed certificate for each domain"
  value       = { for d, c in google_certificate_manager_certificate.this : d => c.id }
}

output "certificate_names" {
  description = "Name of the certificate for each domain, for gcloud certificate-manager certificates describe"
  value       = { for d, c in google_certificate_manager_certificate.this : d => c.name }
}
