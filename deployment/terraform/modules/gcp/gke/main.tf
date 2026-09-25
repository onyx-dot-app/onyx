locals {
  location = coalesce(var.zonal_location, var.region)

  # GKE adds this taint to a GPU pool itself, but only when a non-GPU pool
  # already exists. On a fresh apply the pools are built in parallel, so the
  # module declares it rather than rely on the order.
  gpu_node_pool = var.enable_gpu_node_pool ? {
    gpu = {
      machine_type   = var.gpu_node_machine_type
      min_count      = 1
      max_count      = 1
      disk_size_gb   = 100
      disk_type      = "pd-balanced"
      labels         = { "onyx.app/gpu" = "true" }
      taints         = [{ key = "nvidia.com/gpu", value = "present", effect = "NO_SCHEDULE" }]
      node_locations = var.gpu_node_locations
    }
  } : {}

  # The label and taint are the ones the chart's sandboxPod defaults select and
  # tolerate, so sandbox pods land here with no extra values.
  sandbox_node_pool = var.enable_sandbox_node_pool ? {
    sandbox = {
      machine_type   = var.sandbox_node_machine_type
      min_count      = var.sandbox_node_min_count
      max_count      = var.sandbox_node_max_count
      disk_size_gb   = var.sandbox_node_disk_size_gb
      disk_type      = "pd-balanced"
      labels         = { "onyx.app/workload" = "sandbox" }
      taints         = [{ key = "workload", value = "sandbox", effect = "NO_SCHEDULE" }]
      node_locations = []
    }
  } : {}

  node_pools = merge(
    {
      for key, pool in var.node_pools : key => pool
      if key != "index" || var.index_node_pool_enabled
    },
    local.gpu_node_pool,
    local.sandbox_node_pool,
  )

  # A service account ID is capped at 30 characters and a cluster name can be
  # 40. Truncating alone would let two long names collide, so a digest of the
  # full name goes in the middle.
  node_service_account_id = length(var.name) <= 24 ? "${var.name}-nodes" : "${substr(var.name, 0, 17)}-${substr(sha1(var.name), 0, 5)}-nodes"

  # The minimum a node needs: ship logs and metrics, and pull images from
  # Artifact Registry. The Compute Engine default account would carry Editor.
  node_service_account_roles = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/monitoring.viewer",
    "roles/stackdriver.resourceMetadata.writer",
    "roles/artifactregistry.reader",
  ])

  workload_pool = "${var.project_id}.svc.id.goog"
}

data "google_project" "this" {
  project_id = var.project_id
}

# --- Node identity -----------------------------------------------------------

resource "google_service_account" "nodes" {
  project      = var.project_id
  account_id   = local.node_service_account_id
  display_name = "GKE nodes for ${var.name}"
}

# Keyed by role name, which is a literal, so the keys are known at plan time.
resource "google_project_iam_member" "nodes" {
  for_each = local.node_service_account_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

# --- Cluster -----------------------------------------------------------------

resource "google_container_cluster" "this" {
  project  = var.project_id
  name     = var.name
  location = local.location

  deletion_protection = var.deletion_protection
  min_master_version  = var.kubernetes_version

  # GKE will not build a cluster without a pool, so it builds a default one
  # and this deletes it. The pools below are managed on their own, where a
  # change replaces one pool instead of the whole cluster.
  remove_default_node_pool = true
  initial_node_count       = 1

  # The default pool lives for a few minutes, but without this it runs as the
  # Compute Engine default account, which some organisations disable.
  node_config {
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  network         = var.network_id
  subnetwork      = var.subnet_id
  networking_mode = "VPC_NATIVE"

  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range_name
    services_secondary_range_name = var.services_range_name
  }

  # Dataplane V2 always enforces NetworkPolicy, so the chart's sandbox
  # policies take effect here without a separate add-on.
  datapath_provider = "ADVANCED_DATAPATH"

  release_channel {
    channel = var.release_channel
  }

  workload_identity_config {
    workload_pool = local.workload_pool
  }

  # Nodes get no public address and reach the control plane privately. With
  # no master CIDR set, GKE connects the control plane through Private Service
  # Connect rather than VPC peering.
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = var.private_endpoint_enabled
  }

  dynamic "master_authorized_networks_config" {
    for_each = length(var.master_authorized_networks) > 0 ? [1] : []
    content {
      # Left on, this also admits every Google Cloud public address, which
      # includes VMs any other customer can rent.
      gcp_public_cidrs_access_enabled = false

      dynamic "cidr_blocks" {
        for_each = var.master_authorized_networks
        content {
          cidr_block   = cidr_blocks.value.cidr_block
          display_name = cidr_blocks.value.display_name
        }
      }
    }
  }

  enable_shielded_nodes = true

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  # WORKLOADS is not offered for monitoring any more; workload metrics come
  # from Managed Prometheus, which GKE turns on for new clusters.
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
  }

  # The Gateway API controller is what a later L7 load balancer and Cloud
  # Armor policy attach through.
  gateway_api_config {
    channel = "CHANNEL_STANDARD"
  }

  addons_config {
    http_load_balancing {
      disabled = false
    }

    gce_persistent_disk_csi_driver_config {
      enabled = true
    }
  }

  security_posture_config {
    mode = "BASIC"
  }

  binary_authorization {
    evaluation_mode = "DISABLED"
  }

  resource_labels = var.labels

  lifecycle {
    # node_config describes the default pool, which is gone after create. Left
    # managed, any change to it would replace the whole cluster.
    ignore_changes = [node_config, initial_node_count]
  }

  # Nodes boot as the node account, and without its roles they cannot pull
  # images or ship logs until the grants land.
  depends_on = [google_project_iam_member.nodes]
}

resource "google_container_node_pool" "this" {
  for_each = local.node_pools

  project  = var.project_id
  cluster  = google_container_cluster.this.id
  location = local.location

  # Most node settings cannot change in place. A generated name lets the new
  # pool come up before the old one drains, instead of all of its workloads
  # being evicted at once. Quota has to cover both pools for that time.
  name_prefix = "${each.key}-"

  node_locations = length(each.value.node_locations) > 0 ? each.value.node_locations : null

  # Counted per zone, so one here is three nodes on a regional cluster. A
  # tainted pool starts empty: only pods that ask for it can use it, and those
  # pods make the autoscaler add a node. That keeps a regional GPU pool from
  # asking for a GPU in every zone before it settles to one.
  initial_node_count = length(each.value.taints) == 0 && each.value.min_count > 0 ? 1 : 0

  # The totals count the whole pool. The per-zone form would triple every
  # number on a regional cluster.
  autoscaling {
    total_min_node_count = each.value.min_count
    total_max_node_count = each.value.max_count
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  upgrade_settings {
    strategy        = "SURGE"
    max_surge       = var.node_pool_max_surge
    max_unavailable = 0
  }

  node_config {
    machine_type    = each.value.machine_type
    image_type      = "COS_CONTAINERD"
    disk_size_gb    = each.value.disk_size_gb
    disk_type       = each.value.disk_type
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]

    labels          = each.value.labels
    resource_labels = var.labels

    dynamic "taint" {
      for_each = each.value.taints
      content {
        key    = taint.value.key
        value  = taint.value.value
        effect = taint.value.effect
      }
    }

    dynamic "guest_accelerator" {
      for_each = each.key == "gpu" && var.enable_gpu_node_pool ? [1] : []
      content {
        type  = var.gpu_accelerator_type
        count = var.gpu_accelerator_count

        gpu_driver_installation_config {
          gpu_driver_version = var.gpu_driver_version
        }
      }
    }

    dynamic "sandbox_config" {
      for_each = each.key == "sandbox" && var.enable_sandbox_node_pool && var.sandbox_gvisor_enabled ? [1] : []
      content {
        type = "GVISOR"
      }
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    # Pods see the GKE metadata server, which hands out only the identity of
    # their own service account, never the node's.
    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    # The read-only port serves pod specs with no authentication.
    kubelet_config {
      insecure_kubelet_readonly_port_enabled = "FALSE"
    }
  }

  lifecycle {
    create_before_destroy = true
    # Only read at create. A later change would otherwise replace the pool.
    ignore_changes = [initial_node_count]
  }
}

# --- Workload identity -------------------------------------------------------

# Created before the service account below, which cannot exist without it. The
# documented Helm install then targets this namespace rather than making its own.
resource "kubernetes_namespace" "workload" {
  count = var.create_workload_namespace ? 1 : 0

  metadata {
    name = var.workload_namespace
  }

  depends_on = [google_container_cluster.this]
}

# No annotation: IAM grants name this account directly through the
# workload_identity_principal output, so there is no Google account to map to.
resource "kubernetes_service_account" "workload" {
  count = var.create_workload_service_account ? 1 : 0

  metadata {
    name = var.workload_service_account_name
    # Reading the name back off the namespace is what orders this after it.
    namespace = var.create_workload_namespace ? kubernetes_namespace.workload[0].metadata[0].name : var.workload_namespace
  }

  depends_on = [google_container_cluster.this]
}
