# Plans the module against mocked providers, so these run without a GCP
# project or a cluster. Run with `terraform test` from the module directory.

mock_provider "google" {
  # The workload identity principal is written with the project number, and
  # a mocked random string would make its format impossible to check.
  override_data {
    target = data.google_project.this
    values = {
      number = "123456789012"
    }
  }

  # Known at plan so the tests can check every pool runs as this account.
  override_resource {
    target          = google_service_account.nodes
    override_during = plan
    values = {
      email = "onyx-nodes@example-project.iam.gserviceaccount.com"
    }
  }
}

mock_provider "kubernetes" {}

variables {
  name                = "onyx"
  project_id          = "example-project"
  region              = "us-east1"
  network_id          = "projects/example-project/global/networks/onyx"
  subnet_id           = "projects/example-project/regions/us-east1/subnetworks/onyx"
  pods_range_name     = "onyx-pods"
  services_range_name = "onyx-services"

  # The module refuses a public API server that no network restricts, so every
  # case below has to say what it wants. This is the ordinary answer.
  master_authorized_networks = [{ cidr_block = "203.0.113.0/24", display_name = "office" }]
}

run "defaults_are_secure" {
  command = plan

  assert {
    condition     = google_container_cluster.this.deletion_protection == true
    error_message = "The cluster must refuse a destroy unless deletion_protection is turned off first."
  }

  assert {
    condition     = one(google_container_cluster.this.private_cluster_config).enable_private_nodes == true
    error_message = "Nodes must get no public address."
  }

  assert {
    condition     = one(google_container_cluster.this.private_cluster_config).enable_private_endpoint == false
    error_message = "The public endpoint stays on by default, restricted by the authorized networks."
  }

  assert {
    condition     = one(google_container_cluster.this.master_authorized_networks_config).gcp_public_cidrs_access_enabled == false
    error_message = "Google Cloud public addresses include VMs anyone can rent, so they must not be let in."
  }

  assert {
    condition     = [for c in one(google_container_cluster.this.master_authorized_networks_config).cidr_blocks : c.cidr_block] == ["203.0.113.0/24"]
    error_message = "The authorized networks should be exactly the ones supplied."
  }

  assert {
    condition     = google_container_cluster.this.enable_shielded_nodes == true
    error_message = "Shielded nodes should be on."
  }

  assert {
    condition     = one(google_container_cluster.this.workload_identity_config).workload_pool == "example-project.svc.id.goog"
    error_message = "Workload identity is how a pod reaches GCP without a key."
  }

  assert {
    condition     = one(google_container_cluster.this.binary_authorization).evaluation_mode == "DISABLED"
    error_message = "Binary authorization is off until images are signed."
  }

  assert {
    condition     = one(google_container_cluster.this.security_posture_config).mode == "BASIC"
    error_message = "Security posture should run in BASIC mode."
  }
}

run "cluster_shape_matches_the_contract" {
  command = plan

  assert {
    condition     = google_container_cluster.this.location == "us-east1"
    error_message = "The cluster should be regional by default."
  }

  assert {
    condition     = google_container_cluster.this.remove_default_node_pool == true
    error_message = "The default pool must go, so every pool is managed on its own."
  }

  assert {
    condition     = google_container_cluster.this.datapath_provider == "ADVANCED_DATAPATH"
    error_message = "Dataplane V2 is what enforces the chart's NetworkPolicies."
  }

  assert {
    condition     = one(google_container_cluster.this.release_channel).channel == "REGULAR"
    error_message = "The cluster should follow the REGULAR channel."
  }

  assert {
    condition     = one(google_container_cluster.this.ip_allocation_policy).cluster_secondary_range_name == "onyx-pods" && one(google_container_cluster.this.ip_allocation_policy).services_secondary_range_name == "onyx-services"
    error_message = "Pods and services must draw from the subnet's secondary ranges."
  }

  assert {
    condition     = one(google_container_cluster.this.gateway_api_config).channel == "CHANNEL_STANDARD"
    error_message = "The Gateway API is what a later L7 load balancer attaches through."
  }

  assert {
    condition     = one(one(google_container_cluster.this.addons_config).http_load_balancing).disabled == false
    error_message = "HTTP load balancing must stay on for an L7 ingress."
  }

  assert {
    condition     = one(one(google_container_cluster.this.addons_config).gce_persistent_disk_csi_driver_config).enabled == true
    error_message = "The index and other stateful pods need the persistent disk driver."
  }

  assert {
    condition     = one(google_container_cluster.this.logging_config).enable_components == tolist(["SYSTEM_COMPONENTS", "WORKLOADS"])
    error_message = "Workload logs should go to Cloud Logging."
  }

  assert {
    condition     = one(google_container_cluster.this.node_config).service_account == google_service_account.nodes.email
    error_message = "Even the short-lived default pool must not run as the Compute Engine default account."
  }
}

run "default_pools_are_main_and_index" {
  command = plan

  assert {
    condition     = toset(keys(google_container_node_pool.this)) == toset(["main", "index"])
    error_message = "By default only main and the document-index pool should exist."
  }

  assert {
    condition     = length(one(google_container_node_pool.this["main"].node_config).taint) == 0
    error_message = "System pods tolerate no custom taint, so main must stay untainted."
  }

  assert {
    condition     = google_container_node_pool.this["index"].node_config[0].labels["onyx.app/workload"] == "document-index"
    error_message = "The index pool label must match the Azure module so one set of chart values works on both."
  }

  assert {
    condition = [for t in google_container_node_pool.this["index"].node_config[0].taint : "${t.key}=${t.value}:${t.effect}"] == [
      "document-index=true:NO_SCHEDULE",
    ]
    error_message = "The index pool taint must match the Azure module's document-index=true:NoSchedule."
  }

  assert {
    condition     = google_container_node_pool.this["index"].node_config[0].machine_type == "n2-highmem-4" && google_container_node_pool.this["index"].node_config[0].disk_size_gb == 200
    error_message = "The index pool is memory-optimised and carries a larger disk."
  }
}

run "autoscaling_counts_the_whole_pool" {
  command = plan

  assert {
    condition     = one(google_container_node_pool.this["main"].autoscaling).total_min_node_count == 1 && one(google_container_node_pool.this["main"].autoscaling).total_max_node_count == 5
    error_message = "main should scale between 1 and 5 nodes in total."
  }

  # The per-zone form would triple every number on a regional cluster.
  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(p.autoscaling).min_node_count == null && one(p.autoscaling).max_node_count == null])
    error_message = "Pools must use the total counts, not the per-zone ones."
  }

  assert {
    condition     = google_container_node_pool.this["main"].initial_node_count == 1
    error_message = "main should start with a node per zone so system pods can run at once."
  }

  assert {
    condition     = google_container_node_pool.this["index"].initial_node_count == 0
    error_message = "A tainted pool should start empty and grow when a pod asks for it."
  }
}

run "every_pool_is_hardened" {
  command = plan

  variables {
    enable_gpu_node_pool     = true
    enable_sandbox_node_pool = true
    labels                   = { team = "platform" }
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(one(p.node_config).workload_metadata_config).mode == "GKE_METADATA"])
    error_message = "Pods must see the GKE metadata server, never the node's identity."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(one(p.node_config).shielded_instance_config).enable_secure_boot && one(one(p.node_config).shielded_instance_config).enable_integrity_monitoring])
    error_message = "Every pool should use secure boot and integrity monitoring."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(p.node_config).image_type == "COS_CONTAINERD"])
    error_message = "Every pool should run Container-Optimized OS; gVisor needs it too."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(p.node_config).service_account == google_service_account.nodes.email])
    error_message = "Every pool must run as the dedicated node account."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(one(p.node_config).kubelet_config).insecure_kubelet_readonly_port_enabled == "FALSE"])
    error_message = "The kubelet read-only port serves pod specs without authentication."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(p.node_config).resource_labels == tomap({ team = "platform" })])
    error_message = "Node VMs should carry the caller's labels."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(p.management).auto_repair && one(p.management).auto_upgrade])
    error_message = "A release channel needs auto-upgrade, and broken nodes should be replaced."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : one(p.upgrade_settings).max_surge == 1 && one(p.upgrade_settings).max_unavailable == 0])
    error_message = "Upgrades should surge one node and take none away."
  }

  assert {
    condition     = google_container_cluster.this.resource_labels == tomap({ team = "platform" })
    error_message = "The cluster should carry the caller's labels."
  }
}

run "index_pool_can_be_turned_off" {
  command = plan

  variables {
    index_node_pool_enabled = false
  }

  assert {
    condition     = keys(google_container_node_pool.this) == ["main"]
    error_message = "Turning the index pool off should leave only main."
  }
}

run "optional_pools_are_tainted_and_labelled" {
  command = plan

  variables {
    enable_gpu_node_pool     = true
    enable_sandbox_node_pool = true
  }

  assert {
    condition     = length(google_container_node_pool.this) == 4
    error_message = "main, index, gpu and sandbox should all be present."
  }

  # GKE adds this taint itself only when a non-GPU pool already exists, and
  # on a fresh apply the pools are built in parallel.
  assert {
    condition = [for t in google_container_node_pool.this["gpu"].node_config[0].taint : "${t.key}=${t.value}:${t.effect}"] == [
      "nvidia.com/gpu=present:NO_SCHEDULE",
    ]
    error_message = "The GPU pool must carry the taint GKE uses for GPU nodes."
  }

  assert {
    condition     = google_container_node_pool.this["gpu"].node_config[0].labels["onyx.app/gpu"] == "true"
    error_message = "The GPU pool carries the same label as on AWS and Azure."
  }

  assert {
    condition     = one(google_container_node_pool.this["gpu"].node_config[0].guest_accelerator).type == "nvidia-l4" && one(google_container_node_pool.this["gpu"].node_config[0].guest_accelerator).count == 1
    error_message = "The GPU pool should attach one L4 per node."
  }

  assert {
    condition     = one(one(google_container_node_pool.this["gpu"].node_config[0].guest_accelerator).gpu_driver_installation_config).gpu_driver_version == "LATEST"
    error_message = "GKE should install the GPU driver, so nothing extra has to run in the cluster."
  }

  assert {
    condition     = google_container_node_pool.this["sandbox"].node_config[0].labels["onyx.app/workload"] == "sandbox"
    error_message = "The chart's sandbox pods select their pool by this label."
  }

  assert {
    condition = [for t in google_container_node_pool.this["sandbox"].node_config[0].taint : "${t.key}=${t.value}:${t.effect}"] == [
      "workload=sandbox:NO_SCHEDULE",
    ]
    error_message = "The sandbox taint must be the one the chart's sandboxPod tolerations match."
  }

  assert {
    condition     = length(google_container_node_pool.this["sandbox"].node_config[0].sandbox_config) == 0
    error_message = "gVisor stays off until the chart sets runtimeClassName, or sandbox pods would never schedule."
  }

  assert {
    condition     = length(google_container_node_pool.this["main"].node_config[0].guest_accelerator) == 0
    error_message = "Only the GPU pool should carry a GPU."
  }

  assert {
    condition     = google_container_node_pool.this["gpu"].initial_node_count == 0
    error_message = "A regional GPU pool must not ask for a GPU in every zone before it settles."
  }
}

run "gvisor_can_be_turned_on" {
  command = plan

  variables {
    enable_sandbox_node_pool = true
    sandbox_gvisor_enabled   = true
  }

  assert {
    condition     = one(google_container_node_pool.this["sandbox"].node_config[0].sandbox_config).type == "GVISOR"
    error_message = "The sandbox pool should run under gVisor when asked."
  }

  assert {
    condition     = length(google_container_node_pool.this["main"].node_config[0].sandbox_config) == 0
    error_message = "Only the sandbox pool should run under gVisor."
  }
}

run "the_gpu_pool_can_be_held_to_zones_that_stock_the_gpu" {
  command = plan

  variables {
    enable_gpu_node_pool = true
    gpu_node_locations   = ["us-east1-c"]
  }

  assert {
    condition     = google_container_node_pool.this["gpu"].node_locations == toset(["us-east1-c"])
    error_message = "The GPU pool should be held to the listed zones."
  }
}

run "a_zonal_cluster_can_be_asked_for" {
  command = plan

  variables {
    zonal_location = "us-east1-b"
  }

  assert {
    condition     = google_container_cluster.this.location == "us-east1-b"
    error_message = "zonal_location should build a zonal cluster."
  }

  assert {
    condition     = alltrue([for p in google_container_node_pool.this : p.location == "us-east1-b"])
    error_message = "Pools must be built where the cluster is."
  }
}

run "pools_are_replaced_by_building_the_new_one_first" {
  command = plan

  assert {
    condition     = alltrue([for k, p in google_container_node_pool.this : p.name_prefix == "${k}-"])
    error_message = "A generated name is what lets a replacement pool come up before the old one drains."
  }
}

run "the_node_account_holds_only_the_roles_nodes_need" {
  command = plan

  assert {
    condition = toset([for m in google_project_iam_member.nodes : m.role]) == toset([
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
      "roles/monitoring.viewer",
      "roles/stackdriver.resourceMetadata.writer",
      "roles/artifactregistry.reader",
    ])
    error_message = "The node account should hold exactly the minimal node roles."
  }

  assert {
    condition     = google_service_account.nodes.account_id == "onyx-nodes"
    error_message = "A short cluster name should give <name>-nodes."
  }
}

run "a_long_cluster_name_still_gives_a_valid_node_account_id" {
  command = plan

  variables {
    name = "onyx-production-cluster-name-of-forty-c"
  }

  assert {
    condition     = can(regex("^[a-z][-a-z0-9]{4,28}[a-z0-9]$", google_service_account.nodes.account_id))
    error_message = "A service account ID must be 6-30 characters and start with a letter."
  }

  assert {
    condition     = google_service_account.nodes.account_id != "onyx-production-c-nodes"
    error_message = "The ID must carry a digest, or two long names sharing a prefix would collide."
  }
}

run "the_workload_principal_names_the_service_account" {
  command = plan

  override_resource {
    target          = google_container_cluster.this
    override_during = plan
    values = {
      endpoint = "203.0.113.10"
    }
  }

  assert {
    condition     = output.workload_identity_principal == "principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/example-project.svc.id.goog/subject/ns/onyx/sa/onyx-workload-access"
    error_message = "IAM names a Kubernetes service account by project number, pool, namespace and name."
  }

  assert {
    condition     = output.workload_namespace == "onyx" && output.workload_service_account_name == "onyx-workload-access"
    error_message = "The outputs should name the namespace and service account the principal refers to."
  }

  assert {
    condition     = output.endpoint == "https://203.0.113.10"
    error_message = "The endpoint is handed to the kubernetes provider as a URL."
  }
}

run "the_namespace_is_created_before_the_service_account" {
  command = plan

  assert {
    condition     = kubernetes_namespace.workload[0].metadata[0].name == "onyx"
    error_message = "On a fresh cluster nothing else has made the namespace, and the service account cannot exist without it."
  }

  assert {
    condition     = kubernetes_service_account.workload[0].metadata[0].namespace == "onyx"
    error_message = "The service account should live in the namespace the module creates."
  }

  # GKE federates the account straight to IAM, so an annotation pointing at a
  # Google service account would suggest a mapping that does not exist.
  assert {
    condition     = length(coalesce(kubernetes_service_account.workload[0].metadata[0].annotations, {})) == 0
    error_message = "The service account needs no workload identity annotation."
  }
}

run "the_namespace_can_be_left_to_something_else" {
  command = plan

  variables {
    create_workload_namespace = false
    workload_namespace        = "onyx-prod"
  }

  assert {
    condition     = length(kubernetes_namespace.workload) == 0
    error_message = "A caller whose namespace already exists should not have a second one created."
  }

  assert {
    condition     = kubernetes_service_account.workload[0].metadata[0].namespace == "onyx-prod"
    error_message = "The service account is still created, in the caller's namespace."
  }

  assert {
    condition     = endswith(output.workload_identity_principal, "/subject/ns/onyx-prod/sa/onyx-workload-access")
    error_message = "The principal must follow the namespace the caller chose."
  }
}

run "the_service_account_can_be_left_to_the_chart" {
  command = plan

  variables {
    create_workload_service_account = false
  }

  assert {
    condition     = length(kubernetes_service_account.workload) == 0
    error_message = "A chart-created service account should not be created twice."
  }

  assert {
    condition     = output.workload_service_account_name == "onyx-workload-access"
    error_message = "The output should still name the account IAM grants reach."
  }
}

run "rejects_an_open_control_plane" {
  command = plan

  variables {
    master_authorized_networks = []
  }

  expect_failures = [var.allow_unrestricted_api_server_access]
}

run "an_open_control_plane_can_be_asked_for_explicitly" {
  command = plan

  variables {
    master_authorized_networks           = []
    allow_unrestricted_api_server_access = true
  }

  assert {
    condition     = length(google_container_cluster.this.master_authorized_networks_config) == 0
    error_message = "With no networks there is no restriction to write."
  }
}

run "a_private_endpoint_needs_no_networks" {
  command = plan

  variables {
    master_authorized_networks = []
    private_endpoint_enabled   = true
  }

  assert {
    condition     = one(google_container_cluster.this.private_cluster_config).enable_private_endpoint == true
    error_message = "A private endpoint is the other way to satisfy the rule."
  }
}

run "rejects_a_bad_authorized_network" {
  command = plan

  variables {
    master_authorized_networks = [{ cidr_block = "203.0.113.0/33" }]
  }

  expect_failures = [var.master_authorized_networks]
}

run "rejects_a_cluster_name_gke_would_reject" {
  command = plan

  variables {
    name = "Onyx_Prod"
  }

  expect_failures = [var.name]
}

run "rejects_a_bad_project_id" {
  command = plan

  variables {
    project_id = "1-bad"
  }

  expect_failures = [var.project_id]
}

run "rejects_a_zone_outside_the_region" {
  command = plan

  variables {
    zonal_location = "us-west1-a"
  }

  expect_failures = [var.zonal_location]
}

run "rejects_a_gpu_zone_outside_the_region" {
  command = plan

  variables {
    enable_gpu_node_pool = true
    gpu_node_locations   = ["us-west1-a"]
  }

  expect_failures = [var.gpu_node_locations]
}

run "rejects_a_channel_that_turns_off_upgrades" {
  command = plan

  variables {
    release_channel = "UNSPECIFIED"
  }

  expect_failures = [var.release_channel]
}

run "rejects_a_malformed_kubernetes_version" {
  command = plan

  variables {
    kubernetes_version = "latest"
  }

  expect_failures = [var.kubernetes_version]
}

run "rejects_one_range_for_pods_and_services" {
  command = plan

  variables {
    services_range_name = "onyx-pods"
  }

  expect_failures = [var.services_range_name]
}

run "rejects_node_pools_without_main" {
  command = plan

  variables {
    node_pools = {
      workers = { machine_type = "n2-standard-8" }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_taints_on_main" {
  command = plan

  variables {
    node_pools = {
      main = {
        taints = [{ key = "dedicated", value = "onyx", effect = "NO_SCHEDULE" }]
      }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_pool_key_too_long_for_a_generated_name" {
  command = plan

  variables {
    node_pools = {
      main               = {}
      documentindexpool1 = {}
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_pool_whose_max_is_below_its_min" {
  command = plan

  variables {
    node_pools = {
      main = { min_count = 5, max_count = 2 }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_kubernetes_style_taint_effect" {
  command = plan

  variables {
    node_pools = {
      main  = {}
      index = { taints = [{ key = "document-index", value = "true", effect = "NoSchedule" }] }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_pool_zone_outside_the_region" {
  command = plan

  variables {
    node_pools = {
      main = { node_locations = ["us-west1-a"] }
    }
  }

  expect_failures = [var.node_pools]
}

run "rejects_a_gpu_pool_that_would_replace_a_defined_one" {
  command = plan

  variables {
    enable_gpu_node_pool = true
    node_pools = {
      main = {}
      gpu  = {}
    }
  }

  expect_failures = [var.enable_gpu_node_pool]
}

run "rejects_a_sandbox_pool_that_would_replace_a_defined_one" {
  command = plan

  variables {
    enable_sandbox_node_pool = true
    node_pools = {
      main    = {}
      sandbox = {}
    }
  }

  expect_failures = [var.enable_sandbox_node_pool]
}

run "rejects_a_sandbox_disk_too_small_for_one_pod" {
  command = plan

  variables {
    sandbox_node_disk_size_gb = 20
  }

  expect_failures = [var.sandbox_node_disk_size_gb]
}

run "rejects_an_unknown_gpu_driver_version" {
  command = plan

  variables {
    gpu_driver_version = "535"
  }

  expect_failures = [var.gpu_driver_version]
}

run "rejects_uppercase_labels" {
  command = plan

  variables {
    labels = { Team = "Platform" }
  }

  expect_failures = [var.labels]
}

run "rejects_a_namespace_kubernetes_would_reject" {
  command = plan

  variables {
    workload_namespace = "Onyx_Prod"
  }

  expect_failures = [var.workload_namespace]
}
