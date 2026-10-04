# GCP side of a global external Application Load Balancer that the GKE
# Gateway API builds. The Gateway (class gke-l7-global-external-managed) names
# the address and the certificate map below; the README has the Kubernetes
# objects. Terraform does not create those objects: they are CRDs, and a
# kubernetes_manifest of a CRD fails the plan of a new cluster.
#
# The load balancer terminates TLS, so a Cloud Armor policy can attach to its
# backend service through a GCPBackendPolicy.

locals {
  lb_name = "${var.name}-l7"

  # Certificate Manager names allow 63 characters and no dots, so each domain
  # gets a short digest. The digest depends on the domain only, so adding or
  # removing another domain does not rename, and so replace, this one.
  domain_keys = { for d in var.domains : d => "${local.lb_name}-${substr(sha1(d), 0, 8)}" }

  deletion_policy = var.deletion_protection ? "PREVENT" : "DELETE"
}

# Global addresses are always Premium tier, so the resource has no
# network_tier argument.
resource "google_compute_global_address" "this" {
  project      = var.project_id
  name         = local.lb_name
  description  = "L7 load balancer address for ${var.name}"
  address_type = "EXTERNAL"
  ip_version   = "IPV4"
  labels       = var.labels

  deletion_policy = local.deletion_policy
}

resource "google_certificate_manager_dns_authorization" "this" {
  for_each = local.domain_keys

  project     = var.project_id
  name        = each.value
  location    = "global"
  description = "DNS authorization for ${each.key}"
  domain      = each.key
  type        = "FIXED_RECORD"
  labels      = var.labels

  deletion_policy = local.deletion_policy
}

# One certificate per domain rather than one for all of them. A managed
# certificate cannot change its domains in place, and a replacement serves
# nothing until Google issues it, so a shared certificate would take every
# host offline each time the domain list changes.
resource "google_certificate_manager_certificate" "this" {
  for_each = local.domain_keys

  project     = var.project_id
  name        = each.value
  location    = "global"
  description = "Managed certificate for ${each.key}"
  scope       = "DEFAULT"
  labels      = var.labels

  managed {
    domains            = [each.key]
    dns_authorizations = [google_certificate_manager_dns_authorization.this[each.key].id]
  }
}

resource "google_certificate_manager_certificate_map" "this" {
  project     = var.project_id
  name        = local.lb_name
  description = "Certificate map for the ${var.name} Gateway"
  labels      = var.labels
}

resource "google_certificate_manager_certificate_map_entry" "this" {
  for_each = local.domain_keys

  project      = var.project_id
  name         = each.value
  description  = "Serves the certificate for ${each.key}"
  map          = google_certificate_manager_certificate_map.this.name
  hostname     = each.key
  certificates = [google_certificate_manager_certificate.this[each.key].id]
  labels       = var.labels
}
