output "instance_name" {
  description = "Name of the Cloud SQL instance"
  value       = google_sql_database_instance.this.name
}

output "connection_name" {
  description = "Connection name in the form <project>:<region>:<instance>, for the Cloud SQL Auth Proxy and connectors"
  value       = google_sql_database_instance.this.connection_name
}

output "private_ip_address" {
  description = "Private IP of the instance. Reachable only from the peered VPC."
  value       = google_sql_database_instance.this.private_ip_address
}

output "host" {
  description = "Address Onyx connects to (POSTGRES_HOST). The same as private_ip_address."
  value       = google_sql_database_instance.this.private_ip_address
}

output "port" {
  description = "Port the instance listens on (POSTGRES_PORT)"
  value       = 5432
}

# Reported from the variable rather than the resource, because a database the
# instance ships is not one this module creates.
output "db_name" {
  description = "Database Onyx connects to (POSTGRES_DB), whether this module created it or Cloud SQL shipped it"
  value       = var.db_name

  depends_on = [google_sql_database.this]
}

output "username" {
  description = "Login Onyx connects as (POSTGRES_USER)"
  value       = var.username

  depends_on = [google_sql_user.this]
}

# The provider marks the whole block sensitive, but a CA certificate is public.
# Mount it for the chart's postgresTls option to verify the server (verify-ca).
output "server_ca_cert" {
  description = "PEM of the CA that signed the instance's server certificate"
  value       = nonsensitive(google_sql_database_instance.this.server_ca_cert[0].cert)
}
