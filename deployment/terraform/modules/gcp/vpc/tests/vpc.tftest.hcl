# Plans the module against a mocked provider, so these run without a GCP
# project or credentials. Run with `terraform test` from the module directory.

mock_provider "google" {}

variables {
  name       = "onyx"
  project_id = "example-project"
  region     = "us-east1"
}

run "defaults_are_private_and_custom_mode" {
  command = plan

  assert {
    condition     = google_compute_network.this.auto_create_subnetworks == false
    error_message = "The network must be custom mode so it holds only the subnet this module creates."
  }

  assert {
    condition     = google_compute_network.this.routing_mode == "REGIONAL"
    error_message = "Routing mode should be REGIONAL."
  }

  assert {
    condition     = google_compute_subnetwork.this.private_ip_google_access == true
    error_message = "Private nodes need Private Google Access to reach Google APIs."
  }

  assert {
    condition     = google_compute_subnetwork.this.ip_cidr_range == "10.0.0.0/20"
    error_message = "The subnet should default to 10.0.0.0/20."
  }

  assert {
    condition = {
      for r in google_compute_subnetwork.this.secondary_ip_range : r.range_name => r.ip_cidr_range
    } == { "onyx-pods" = "10.4.0.0/14", "onyx-services" = "10.8.0.0/20" }
    error_message = "The subnet should carry the pods and services secondary ranges under the names GKE is given."
  }

  assert {
    condition     = output.pods_range_name == "onyx-pods" && output.services_range_name == "onyx-services"
    error_message = "The range-name outputs must match the secondary ranges on the subnet."
  }
}

run "flow_logs_on_by_default" {
  command = plan

  assert {
    condition     = length(google_compute_subnetwork.this.log_config) == 1
    error_message = "Flow logs should be on by default."
  }

  assert {
    condition     = google_compute_subnetwork.this.log_config[0].flow_sampling == 0.5
    error_message = "Flow log sampling should default to 0.5."
  }
}

run "flow_logs_can_be_disabled" {
  command = plan

  variables {
    enable_flow_logs = false
  }

  assert {
    condition     = length(google_compute_subnetwork.this.log_config) == 0
    error_message = "enable_flow_logs = false should drop the subnet log_config."
  }
}

run "nat_covers_the_subnet_and_logs_errors" {
  command = plan

  assert {
    condition     = google_compute_router_nat.this.nat_ip_allocate_option == "AUTO_ONLY"
    error_message = "The NAT should use Google-allocated addresses."
  }

  assert {
    condition     = google_compute_router_nat.this.source_subnetwork_ip_ranges_to_nat == "LIST_OF_SUBNETWORKS"
    error_message = "The NAT should name its subnet explicitly."
  }

  assert {
    condition     = one(google_compute_router_nat.this.subnetwork).source_ip_ranges_to_nat == toset(["ALL_IP_RANGES"])
    error_message = "The NAT must cover the pod secondary range as well as the node range."
  }

  assert {
    condition     = google_compute_router_nat.this.log_config[0].enable && google_compute_router_nat.this.log_config[0].filter == "ERRORS_ONLY"
    error_message = "NAT logging should be on, errors only."
  }

  assert {
    condition     = google_compute_router_nat.this.enable_dynamic_port_allocation == true && google_compute_router_nat.this.enable_endpoint_independent_mapping == false
    error_message = "Dynamic port allocation should be on, which needs endpoint-independent mapping off."
  }

  assert {
    condition     = google_compute_router_nat.this.router == "onyx-router"
    error_message = "The NAT should live on the module's router."
  }
}

run "private_service_access_is_reserved_and_peered" {
  command = apply

  variables {
    labels = { env = "test" }
  }

  assert {
    condition     = google_compute_global_address.private_service_access.purpose == "VPC_PEERING" && google_compute_global_address.private_service_access.prefix_length == 16
    error_message = "Private Service Access should reserve a /16 VPC_PEERING range by default."
  }

  assert {
    condition     = google_compute_global_address.private_service_access.labels == tomap({ env = "test" })
    error_message = "Labels should reach the reserved range."
  }

  assert {
    condition     = google_service_networking_connection.this.service == "servicenetworking.googleapis.com"
    error_message = "The peering should be with Service Networking."
  }

  assert {
    condition     = google_service_networking_connection.this.reserved_peering_ranges == tolist([google_compute_global_address.private_service_access.name])
    error_message = "The peering should use the reserved range."
  }

  assert {
    condition     = google_service_networking_connection.this.deletion_policy == "DELETE"
    error_message = "The peering must be deletable, or terraform destroy cannot remove the network."
  }

  assert {
    condition     = output.private_service_access_network_id == output.network_id
    error_message = "private_service_access_network_id must be the network ID."
  }
}

run "psa_prefix_length_is_configurable" {
  command = plan

  variables {
    psa_prefix_length = 20
  }

  assert {
    condition     = google_compute_global_address.private_service_access.prefix_length == 20
    error_message = "psa_prefix_length should size the reserved range."
  }
}

run "custom_non_overlapping_ranges_plan" {
  command = plan

  variables {
    subnet_cidr   = "172.16.0.0/22"
    pods_cidr     = "172.20.0.0/16"
    services_cidr = "172.16.4.0/22"
  }

  assert {
    condition     = google_compute_subnetwork.this.ip_cidr_range == "172.16.0.0/22"
    error_message = "The subnet should use subnet_cidr."
  }
}

run "rejects_pods_overlapping_the_subnet" {
  command = plan

  variables {
    pods_cidr = "10.0.0.0/14"
  }

  expect_failures = [google_compute_subnetwork.this]
}

run "rejects_services_inside_pods" {
  command = plan

  variables {
    services_cidr = "10.5.0.0/20"
  }

  expect_failures = [google_compute_subnetwork.this]
}

run "rejects_services_containing_the_subnet" {
  command = plan

  variables {
    services_cidr = "10.0.0.0/8"
  }

  expect_failures = [google_compute_subnetwork.this]
}

run "rejects_an_unaligned_cidr" {
  command = plan

  variables {
    subnet_cidr = "10.0.0.1/20"
  }

  expect_failures = [var.subnet_cidr]
}

run "rejects_a_non_cidr_pods_range" {
  command = plan

  variables {
    pods_cidr = "not-a-cidr"
  }

  expect_failures = [var.pods_cidr]
}

run "rejects_an_ipv6_services_range" {
  command = plan

  variables {
    services_cidr = "fd00::/64"
  }

  expect_failures = [var.services_cidr]
}

run "rejects_an_invalid_name" {
  command = plan

  variables {
    name = "Onyx_VPC"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_too_long_for_its_suffixes" {
  command = plan

  variables {
    name = "a234567890123456789012345678901234567890123456789012345"
  }

  expect_failures = [var.name]
}

run "rejects_an_invalid_project_id" {
  command = plan

  variables {
    project_id = "Bad_Project"
  }

  expect_failures = [var.project_id]
}

run "rejects_a_zone_as_region" {
  command = plan

  variables {
    region = "us-east1-b"
  }

  expect_failures = [var.region]
}

run "rejects_a_psa_range_too_small_for_cloud_sql" {
  command = plan

  variables {
    psa_prefix_length = 28
  }

  expect_failures = [var.psa_prefix_length]
}

run "rejects_zero_flow_log_sampling" {
  command = plan

  variables {
    flow_log_sampling = 0
  }

  expect_failures = [var.flow_log_sampling]
}

run "rejects_uppercase_labels" {
  command = plan

  variables {
    labels = { Env = "Prod" }
  }

  expect_failures = [var.labels]
}
