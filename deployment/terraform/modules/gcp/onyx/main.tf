locals {
  workspace     = terraform.workspace
  merged_labels = merge(var.labels, { tenant = var.name, environment = local.workspace })

  resource_prefix = "${var.name}-${local.workspace}"
  cluster_name    = local.resource_prefix
  postgres_name   = "${var.name}-postgres-${local.workspace}"
  redis_name      = "${var.name}-redis-${local.workspace}"

  # Bucket names are globally unique across every GCP customer, so the
  # readable prefix is truncated and a short digest of the full identity is
  # appended to keep collisions unlikely.
  bucket_name_digest    = substr(sha1("${var.project_id}-${var.name}-${local.workspace}-${var.region}"), 0, 8)
  bucket_name_sanitized = replace(lower("${local.resource_prefix}-files"), "/[^a-z0-9-]/", "-")
  # 54 + "-" + 8 = 63, the most a bucket name without dots may have.
  bucket_name = coalesce(
    var.bucket_name,
    "${substr(local.bucket_name_sanitized, 0, 54)}-${local.bucket_name_digest}",
  )

  project_apis = var.enable_project_apis ? toset([
    "compute.googleapis.com",
    "container.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com",
    "servicenetworking.googleapis.com",
    "storage.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
    # Project IAM grants for the node service account go through this API.
    "cloudresourcemanager.googleapis.com",
  ]) : toset([])

  # T-shirt size defaults, chosen so each tier lands on the GCP machine closest
  # to what the AWS and Azure compositions pick. The index pool is
  # memory-optimised because on GCP it carries the document index itself:
  # there is no managed OpenSearch to move that load off the cluster.
  size_defaults = {
    small = {
      main_node_machine_type  = "n2-standard-8"
      main_node_min_count     = 1
      main_node_max_count     = 3
      index_node_machine_type = "n2-highmem-4"
      index_node_disk_size_gb = 256
      postgres_tier           = "db-custom-2-8192"
      postgres_disk_size_gb   = 64
      redis_memory_size_gb    = 5
    }
    medium = {
      main_node_machine_type  = "n2-standard-16"
      main_node_min_count     = 1
      main_node_max_count     = 5
      index_node_machine_type = "n2-highmem-8"
      index_node_disk_size_gb = 512
      postgres_tier           = "db-custom-2-8192"
      postgres_disk_size_gb   = 128
      redis_memory_size_gb    = 10
    }
    large = {
      main_node_machine_type  = "n2-standard-16"
      main_node_min_count     = 2
      main_node_max_count     = 8
      index_node_machine_type = "n2-highmem-16"
      index_node_disk_size_gb = 1024
      postgres_tier           = "db-custom-4-16384"
      postgres_disk_size_gb   = 256
      redis_memory_size_gb    = 20
    }
  }
  sizing = local.size_defaults[var.size]

  # An explicitly set variable always wins over its tier default.
  main_node_machine_type  = coalesce(var.main_node_machine_type, local.sizing.main_node_machine_type)
  main_node_min_count     = coalesce(var.main_node_min_count, local.sizing.main_node_min_count)
  main_node_max_count     = coalesce(var.main_node_max_count, local.sizing.main_node_max_count)
  index_node_machine_type = coalesce(var.index_node_machine_type, local.sizing.index_node_machine_type)
  index_node_disk_size_gb = coalesce(var.index_node_disk_size_gb, local.sizing.index_node_disk_size_gb)
  postgres_tier           = coalesce(var.postgres_tier, local.sizing.postgres_tier)
  postgres_disk_size_gb   = coalesce(var.postgres_disk_size_gb, local.sizing.postgres_disk_size_gb)
  redis_memory_size_gb    = coalesce(var.redis_memory_size_gb, local.sizing.redis_memory_size_gb)

  # The index label and taint are the gke module's defaults, which the chart
  # values in the README select and tolerate. The gke module drops this pool
  # when index_node_pool_enabled is false.
  node_pools = {
    main = {
      machine_type = local.main_node_machine_type
      min_count    = local.main_node_min_count
      max_count    = local.main_node_max_count
      disk_size_gb = var.main_node_disk_size_gb
    }
    index = {
      machine_type = local.index_node_machine_type
      min_count    = var.index_node_min_count
      max_count    = var.index_node_max_count
      disk_size_gb = local.index_node_disk_size_gb
      labels       = { "onyx.app/workload" = "document-index" }
      taints       = [{ key = "document-index", value = "true", effect = "NO_SCHEDULE" }]
    }
  }

  # Read per module rather than passed as the bare variable, so the tests can
  # see that every guarded resource follows the one switch.
  deletion_protection = {
    gke         = var.deletion_protection
    postgres    = var.deletion_protection
    redis       = var.deletion_protection
    gcs         = var.deletion_protection
    cloud_armor = var.deletion_protection
  }
}

# The workspace name goes into every resource name, and "<name>-redis-<workspace>"
# must fit Memorystore's 40 characters with a name of up to 24. A precondition
# fails the plan before anything is created; a check block would only warn, and
# the apply would then stop part-way when Memorystore rejects the name.
resource "terraform_data" "workspace_name" {
  lifecycle {
    precondition {
      condition     = can(regex("^[a-z]([a-z0-9-]{0,7}[a-z0-9])?$", local.workspace))
      error_message = "The Terraform workspace name must be 1-9 characters of lowercase letters, digits and hyphens, start with a letter and not end with a hyphen. It goes into every resource name, and Memorystore caps \"<name>-redis-<workspace>\" at 40 characters."
    }
  }
}

resource "google_project_service" "this" {
  for_each = local.project_apis

  project = var.project_id
  service = each.value

  # Other workloads in the project may use the same APIs, and turning one off
  # on destroy breaks them.
  disable_on_destroy = false
}

locals {
  # Reading the project back off the API resources is what orders every
  # module after them. A depends_on on the modules would do it too, but it
  # defers the gke module's project lookup to apply, which makes the bucket
  # grant's principal unknown at plan and fails its for_each.
  project_id = coalesce(one(distinct([for s in google_project_service.this : s.project])), var.project_id)

  network_id          = var.create_network ? module.vpc[0].network_id : var.network_id
  subnet_id           = var.create_network ? module.vpc[0].subnet_id : var.subnet_id
  pods_range_name     = var.create_network ? module.vpc[0].pods_range_name : var.pods_range_name
  services_range_name = var.create_network ? module.vpc[0].services_range_name : var.services_range_name

  # Cloud SQL and Memorystore take the id that arrives only once the Private
  # Service Access peering exists; network_id would let them race it.
  private_service_network_id = var.create_network ? module.vpc[0].private_service_access_network_id : var.network_id

  bucket_object_admin_members = [module.gke.workload_identity_principal]
}

module "vpc" {
  source = "../vpc"
  count  = var.create_network ? 1 : 0

  name       = local.resource_prefix
  project_id = local.project_id
  region     = var.region
  labels     = local.merged_labels

  subnet_cidr       = var.subnet_cidr
  pods_cidr         = var.pods_cidr
  services_cidr     = var.services_cidr
  psa_prefix_length = var.psa_prefix_length
  enable_flow_logs  = var.enable_flow_logs
}

module "gke" {
  source = "../gke"

  name                = local.cluster_name
  project_id          = local.project_id
  region              = var.region
  kubernetes_version  = var.kubernetes_version
  release_channel     = var.release_channel
  deletion_protection = local.deletion_protection.gke
  labels              = local.merged_labels

  network_id          = local.network_id
  subnet_id           = local.subnet_id
  pods_range_name     = local.pods_range_name
  services_range_name = local.services_range_name

  private_endpoint_enabled             = var.private_endpoint_enabled
  master_authorized_networks           = var.master_authorized_networks
  allow_unrestricted_api_server_access = var.allow_unrestricted_api_server_access

  node_pools               = local.node_pools
  index_node_pool_enabled  = var.index_node_pool_enabled
  enable_gpu_node_pool     = var.enable_gpu_node_pool
  enable_sandbox_node_pool = var.enable_sandbox_node_pool

  create_workload_namespace     = var.create_workload_namespace
  workload_namespace            = var.workload_namespace
  workload_service_account_name = var.workload_service_account_name
}

module "gcs" {
  source = "../gcs"

  name                = local.bucket_name
  project_id          = local.project_id
  location            = upper(var.region)
  force_destroy       = var.bucket_force_destroy
  deletion_protection = local.deletion_protection.gcs
  labels              = local.merged_labels

  # Built from inputs inside the gke module, so it is known at plan and safe
  # as a for_each key there.
  object_admin_members = local.bucket_object_admin_members
}

module "postgres" {
  source = "../postgres"

  name                = local.postgres_name
  project_id          = local.project_id
  region              = var.region
  network_id          = local.private_service_network_id
  deletion_protection = local.deletion_protection.postgres
  labels              = local.merged_labels

  database_version  = var.postgres_database_version
  tier              = local.postgres_tier
  disk_size_gb      = local.postgres_disk_size_gb
  availability_type = var.postgres_availability_type
  max_connections   = var.postgres_max_connections

  db_name  = var.postgres_db_name
  username = var.postgres_username
  password = var.postgres_password

  enable_alerts         = var.enable_alerts
  notification_channels = var.notification_channels
}

module "redis" {
  source = "../redis"
  count  = var.enable_redis ? 1 : 0

  name                = local.redis_name
  project_id          = local.project_id
  region              = var.region
  network_id          = local.private_service_network_id
  deletion_protection = local.deletion_protection.redis
  labels              = local.merged_labels

  tier                       = var.redis_tier
  memory_size_gb             = local.redis_memory_size_gb
  transit_encryption_enabled = var.redis_transit_encryption_enabled

  enable_alerts         = var.enable_alerts
  notification_channels = var.notification_channels
}

module "cloud_armor" {
  source = "../cloud-armor"
  count  = var.enable_cloud_armor ? 1 : 0

  name                = local.resource_prefix
  project_id          = local.project_id
  deletion_protection = local.deletion_protection.cloud_armor
  labels              = local.merged_labels

  preview                     = var.cloud_armor_preview
  sensitivity                 = var.cloud_armor_sensitivity
  allowed_ip_cidrs            = var.cloud_armor_allowed_ip_cidrs
  blocked_ip_cidrs            = var.cloud_armor_blocked_ip_cidrs
  rate_limit_exempt_ip_cidrs  = var.cloud_armor_rate_limit_exempt_ip_cidrs
  geo_restriction_countries   = var.cloud_armor_geo_restriction_countries
  rate_limit_threshold        = var.cloud_armor_rate_limit_threshold
  api_rate_limit_threshold    = var.cloud_armor_api_rate_limit_threshold
  adaptive_protection_enabled = var.cloud_armor_adaptive_protection_enabled
}
