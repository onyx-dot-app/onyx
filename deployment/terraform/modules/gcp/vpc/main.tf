locals {
  cidrs = {
    subnet   = var.subnet_cidr
    pods     = var.pods_cidr
    services = var.services_cidr
  }

  # The overlap check only means anything once every range parses. Each
  # range's own validation reports a bad value, so the overlap checks stand
  # down rather than add a second, confusing error.
  cidrs_valid = alltrue([for c in values(local.cidrs) : can(cidrsubnet(c, 0, 0))])

  # Two aligned ranges overlap exactly when they share a network address at
  # the shorter of their two prefix lengths.
  overlaps = local.cidrs_valid ? {
    for pair in [["subnet", "pods"], ["subnet", "services"], ["pods", "services"]] :
    "${pair[0]}_${pair[1]}" => (
      cidrhost("${split("/", local.cidrs[pair[0]])[0]}/${min(tonumber(split("/", local.cidrs[pair[0]])[1]), tonumber(split("/", local.cidrs[pair[1]])[1]))}", 0) ==
      cidrhost("${split("/", local.cidrs[pair[1]])[0]}/${min(tonumber(split("/", local.cidrs[pair[0]])[1]), tonumber(split("/", local.cidrs[pair[1]])[1]))}", 0)
    )
  } : {}

  pods_range_name     = "${var.name}-pods"
  services_range_name = "${var.name}-services"
}

# Custom mode, so the only subnet is the one below rather than one per region
# in 10.128.0.0/9.
resource "google_compute_network" "this" {
  name                    = "${var.name}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "this" {
  name          = "${var.name}-subnet"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.this.id
  ip_cidr_range = var.subnet_cidr

  # Nodes have no public IPs, so Google APIs (GCS, Artifact Registry, Cloud
  # Logging) are reached this way rather than through the NAT.
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = local.pods_range_name
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = local.services_range_name
    ip_cidr_range = var.services_cidr
  }

  # A variable validation may only test its own value, so the cross-range
  # check lives here. It still fails at plan, before anything is created.
  lifecycle {
    precondition {
      condition     = !contains(values(local.overlaps), true)
      error_message = "subnet_cidr, pods_cidr and services_cidr must not overlap. Overlapping pairs: ${join(", ", [for k, v in local.overlaps : k if v])}."
    }
  }

  dynamic "log_config" {
    for_each = var.enable_flow_logs ? [1] : []
    content {
      aggregation_interval = "INTERVAL_5_SEC"
      flow_sampling        = var.flow_log_sampling
      metadata             = "INCLUDE_ALL_METADATA"
    }
  }
}

resource "google_compute_router" "this" {
  name    = "${var.name}-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.this.id
}

# Egress for private nodes and pods. Addresses are Google-allocated, so they
# change if the NAT is recreated; switch to MANUAL_ONLY with reserved
# addresses if a downstream system allowlists the egress IP.
resource "google_compute_router_nat" "this" {
  name                               = "${var.name}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.this.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  # All ranges, not just the primary: pod traffic leaves with a pod IP when
  # it is not masqueraded to the node.
  subnetwork {
    name                    = google_compute_subnetwork.this.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  # The static default of 64 ports per VM is shared by every pod on a node and
  # runs out under connector and LLM traffic. Dynamic allocation grows a busy
  # node's share instead. It requires endpoint-independent mapping off.
  enable_dynamic_port_allocation      = true
  enable_endpoint_independent_mapping = false
  min_ports_per_vm                    = 64
  max_ports_per_vm                    = 4096

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# No firewall rules here. GKE creates the rules its nodes, pods and control
# plane need, and Private Service Access traffic is egress, which the implied
# allow-egress rule already permits.

resource "google_compute_global_address" "private_service_access" {
  name          = "${var.name}-psa"
  project       = var.project_id
  network       = google_compute_network.this.id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.psa_prefix_length
  labels        = var.labels
}

# DELETE, not ABANDON. ABANDON drops the
# connection from state but leaves the peering in place, and the network then
# refuses to delete, so destroy fails one step later instead. Destroy can still
# fail for a while after Cloud SQL is deleted, because the producer holds the
# connection until its own cleanup finishes; retry the destroy.
resource "google_service_networking_connection" "this" {
  network                 = google_compute_network.this.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_access.name]
  deletion_policy         = "DELETE"
}
