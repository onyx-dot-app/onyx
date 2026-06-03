# Plans the whole composition against mocked providers, so these run without a
# GCP project or a cluster. Run with `terraform test` from the module directory.

mock_provider "google" {
  # The workload identity principal is written with the project number, and
  # a mocked random string would make it impossible to check.
  override_data {
    target = module.gke.data.google_project.this
    values = {
      number = "123456789012"
    }
  }
}

mock_provider "kubernetes" {}

variables {
  name              = "onyx"
  project_id        = "example-project"
  region            = "us-east1"
  postgres_password = "not-a-real-password"

  # The composition refuses a public API server that no range restricts, so
  # every case below has to say what it wants.
  master_authorized_networks = [{ cidr_block = "203.0.113.0/24" }]
}

run "medium_is_the_default_tier" {
  command = plan

  assert {
    condition     = local.main_node_machine_type == "n2-standard-16"
    error_message = "Medium should land on the GCP machine closest to the AWS composition's m7i.4xlarge."
  }

  assert {
    condition     = local.main_node_min_count == 1 && local.main_node_max_count == 5
    error_message = "Medium runs 1-5 main nodes, like the Azure composition."
  }

  assert {
    condition     = local.index_node_machine_type == "n2-highmem-8" && local.index_node_disk_size_gb == 512
    error_message = "The index pool is memory-optimised because on GCP it carries the document index itself."
  }

  assert {
    condition     = local.postgres_tier == "db-custom-2-8192" && local.postgres_disk_size_gb == 128
    error_message = "Medium keeps the small database tier, matching the AWS composition."
  }

  assert {
    condition     = local.redis_memory_size_gb == 10
    error_message = "Medium gets a 10 GB cache, like the Azure composition's Balanced_B10."
  }
}

run "small_moves_every_knob_together" {
  command = plan

  variables {
    size = "small"
  }

  assert {
    condition = alltrue([
      local.main_node_machine_type == "n2-standard-8",
      local.main_node_min_count == 1,
      local.main_node_max_count == 3,
      local.index_node_machine_type == "n2-highmem-4",
      local.index_node_disk_size_gb == 256,
      local.postgres_tier == "db-custom-2-8192",
      local.postgres_disk_size_gb == 64,
      local.redis_memory_size_gb == 5,
    ])
    error_message = "The small tier should move compute, database, cache and index sizing together."
  }
}

run "large_moves_every_knob_together" {
  command = plan

  variables {
    size = "large"
  }

  assert {
    condition = alltrue([
      local.main_node_machine_type == "n2-standard-16",
      local.main_node_min_count == 2,
      local.main_node_max_count == 8,
      local.index_node_machine_type == "n2-highmem-16",
      local.index_node_disk_size_gb == 1024,
      local.postgres_tier == "db-custom-4-16384",
      local.postgres_disk_size_gb == 256,
      local.redis_memory_size_gb == 20,
    ])
    error_message = "The large tier should move compute, database, cache and index sizing together."
  }
}

run "an_explicit_value_beats_its_tier_default" {
  command = plan

  variables {
    size                  = "small"
    postgres_disk_size_gb = 512
    main_node_max_count   = 10
    redis_memory_size_gb  = 8
  }

  assert {
    condition     = local.postgres_disk_size_gb == 512 && local.main_node_max_count == 10 && local.redis_memory_size_gb == 8
    error_message = "An explicitly set variable must win over the tier default."
  }

  assert {
    condition     = local.main_node_machine_type == "n2-standard-8"
    error_message = "Overriding one knob must not disturb the others in the tier."
  }

  assert {
    condition     = local.node_pools.main.max_count == 10
    error_message = "The override has to reach the node pool the gke module builds."
  }
}

run "the_derived_bucket_name_is_one_gcs_accepts" {
  command = plan

  assert {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", local.bucket_name))
    error_message = "Bucket names allow 3-63 lowercase letters, digits and hyphens."
  }

  assert {
    condition     = startswith(local.bucket_name, "onyx-default-files-") && endswith(local.bucket_name, local.bucket_name_digest)
    error_message = "The bucket name should read as its deployment and end in the digest."
  }
}

run "a_long_name_keeps_the_whole_digest" {
  command = plan

  # The longest name the composition accepts. Only a long workspace name
  # pushes the prefix past 54 characters, and tests cannot set one.
  variables {
    name = "onyx-enterprise-producti"
  }

  assert {
    condition     = length(local.bucket_name) <= 63 && endswith(local.bucket_name, local.bucket_name_digest)
    error_message = "Truncation must eat the readable prefix, never the digest."
  }
}

run "an_explicit_bucket_name_is_used_as_given" {
  command = plan

  variables {
    bucket_name = "onyx-files-prod"
  }

  assert {
    condition     = output.gcs_bucket_name == "onyx-files-prod"
    error_message = "An explicit bucket name must reach the bucket unchanged."
  }
}

run "deletion_protection_is_on_everywhere_by_default" {
  command = plan

  assert {
    condition     = alltrue(values(local.deletion_protection)) && length(local.deletion_protection) == 5
    error_message = "The cluster, database, cache, bucket and policy must all be protected by default."
  }
}

run "one_switch_turns_deletion_protection_off_everywhere" {
  command = plan

  variables {
    deletion_protection = false
  }

  assert {
    condition     = !anytrue(values(local.deletion_protection))
    error_message = "deletion_protection = false must reach every module, or a teardown stops halfway."
  }
}

run "data_services_wait_for_the_peering" {
  command = plan

  # Distinct ids for the two outputs make the choice visible. In the real vpc
  # module they hold the same string and differ only in when they arrive.
  override_module {
    target = module.vpc
    outputs = {
      network_id                        = "projects/example-project/global/networks/plain"
      private_service_access_network_id = "projects/example-project/global/networks/after-peering"
      subnet_id                         = "projects/example-project/regions/us-east1/subnetworks/onyx-default-subnet"
      pods_range_name                   = "onyx-default-pods"
      services_range_name               = "onyx-default-services"
      network_name                      = "onyx-default-vpc"
      subnet_name                       = "onyx-default-subnet"
    }
  }

  assert {
    condition     = local.private_service_network_id == "projects/example-project/global/networks/after-peering"
    error_message = "Cloud SQL and Memorystore must take the id that waits for Private Service Access, or they race the peering."
  }

  assert {
    condition     = local.network_id == "projects/example-project/global/networks/plain"
    error_message = "The cluster has no reason to wait for the peering."
  }
}

run "the_bucket_grant_goes_to_the_workload_service_account" {
  command = plan

  assert {
    condition     = local.bucket_object_admin_members == ["principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/example-project.svc.id.goog/subject/ns/onyx/sa/onyx-workload-access"]
    error_message = "The bucket should grant the Kubernetes service account the chart runs as, and nothing else."
  }

  # Known at plan is the point: the gcs module keys a for_each on it.
  assert {
    condition     = output.workload_identity_principal == local.bucket_object_admin_members[0]
    error_message = "The published principal must be the one the bucket grants."
  }
}

run "redis_and_cloud_armor_are_on_by_default" {
  command = plan

  assert {
    condition     = length(module.redis) == 1 && length(module.cloud_armor) == 1
    error_message = "Memorystore and Cloud Armor should both be created by default."
  }

  assert {
    condition     = output.redis_url_scheme == "rediss"
    error_message = "The cache serves TLS by default, so the scheme is rediss."
  }

  assert {
    condition     = one(module.redis[*].redis_url_scheme) == "rediss"
    error_message = "The composition must turn on transit encryption in the redis module by default."
  }
}

run "the_server_ca_certificates_are_published" {
  command = plan

  override_module {
    target = module.redis
    outputs = {
      instance_id         = "projects/example-project/locations/us-east1/instances/onyx-redis-default"
      host                = "10.0.0.3"
      port                = 6378
      auth_string         = "not-a-real-auth-string"
      server_ca_certs     = ["redis-ca-pem"]
      current_location_id = "us-east1-b"
      redis_url_scheme    = "rediss"
    }
  }

  override_module {
    target = module.postgres
    outputs = {
      server_ca_cert = "postgres-ca-pem"
    }
  }

  assert {
    condition     = output.redis_server_ca_certs == ["redis-ca-pem"]
    error_message = "The chart's redisTls needs the cache's CA certificates."
  }

  assert {
    condition     = output.postgres_server_ca_cert == "postgres-ca-pem"
    error_message = "The chart's postgresTls needs the database's CA certificate."
  }
}

run "the_default_workspace_name_is_accepted" {
  command = plan

  assert {
    condition     = local.redis_name == "onyx-redis-default"
    error_message = "The workspace guard must not reject the default workspace."
  }
}

run "turning_off_redis_and_cloud_armor_drops_them" {
  command = plan

  variables {
    enable_redis       = false
    enable_cloud_armor = false
  }

  assert {
    condition     = length(module.redis) == 0 && length(module.cloud_armor) == 0
    error_message = "Disabled modules must create nothing."
  }

  assert {
    condition = alltrue([
      output.redis_host == null,
      output.redis_port == null,
      output.redis_url_scheme == null,
      output.redis_server_ca_certs == null,
      output.cloud_armor_policy_name == null,
    ])
    error_message = "With nothing created there is nothing to publish."
  }
}

run "the_project_apis_are_enabled_by_default" {
  command = plan

  assert {
    condition     = length(google_project_service.this) == 10
    error_message = "Every API a module calls should be enabled."
  }

  assert {
    condition     = alltrue([for s in google_project_service.this : !s.disable_on_destroy])
    error_message = "Destroying Onyx must not turn off APIs other workloads in the project may use."
  }
}

run "apis_managed_elsewhere_are_left_alone" {
  command = plan

  variables {
    enable_project_apis = false
  }

  assert {
    condition     = length(google_project_service.this) == 0
    error_message = "enable_project_apis = false must enable nothing."
  }

  assert {
    condition     = local.project_id == "example-project"
    error_message = "With no API resources the modules still need the project."
  }
}

run "an_existing_network_is_used_as_given" {
  command = plan

  variables {
    create_network      = false
    network_id          = "projects/example-project/global/networks/shared"
    subnet_id           = "projects/example-project/regions/us-east1/subnetworks/gke"
    pods_range_name     = "gke-pods"
    services_range_name = "gke-services"
  }

  assert {
    condition     = length(module.vpc) == 0
    error_message = "A supplied network means no network is created."
  }

  assert {
    condition     = local.private_service_network_id == "projects/example-project/global/networks/shared"
    error_message = "The database and cache should join the supplied network."
  }

  assert {
    condition     = output.network_name == "shared" && output.subnet_name == "gke"
    error_message = "The names should be read off the supplied ids."
  }
}

run "bringing_your_own_network_needs_every_id" {
  command = plan

  variables {
    create_network = false
    network_id     = "projects/example-project/global/networks/shared"
  }

  expect_failures = [var.create_network]
}

run "rejects_a_deployment_with_no_database_password" {
  command = plan

  variables {
    postgres_password = null
  }

  expect_failures = [var.postgres_password]
}

run "rejects_an_open_control_plane" {
  command = plan

  variables {
    master_authorized_networks = []
  }

  expect_failures = [var.allow_unrestricted_api_server_access]
}

run "an_open_control_plane_can_be_asked_for" {
  command = plan

  variables {
    master_authorized_networks           = []
    allow_unrestricted_api_server_access = true
  }

  assert {
    condition     = output.cluster_name == "onyx-default"
    error_message = "Recording that the exposure is intended should let the plan through."
  }
}

run "rejects_a_size_that_is_not_a_tier" {
  command = plan

  variables {
    size = "extra-large"
  }

  expect_failures = [var.size]
}
