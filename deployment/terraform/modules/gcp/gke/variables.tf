variable "name" {
  type        = string
  description = "Name of the cluster. Also the prefix of the node service account."

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,38}[a-z0-9])?$", var.name))
    error_message = "name must be 1-40 characters of lowercase letters, digits and hyphens, start with a letter and not end with a hyphen (GKE limit)."
  }
}

variable "project_id" {
  type        = string
  description = "GCP project that holds the cluster"

  validation {
    condition     = can(regex("^[a-z][-a-z0-9]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project ID: 6-30 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  type        = string
  description = "GCP region, for example \"us-east1\". The cluster is regional unless zonal_location is set."

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "region must be a GCP region such as \"us-east1\" or \"europe-west4\"."
  }
}

# A regional control plane is replicated across three zones and carries an SLA;
# a zonal one does not. Zonal is cheaper for throwaway clusters only.
variable "zonal_location" {
  type        = string
  description = "Zone for a zonal cluster, for example \"us-east1-b\". Null builds a regional cluster in region."
  default     = null

  validation {
    condition     = var.zonal_location == null || can(regex("^${var.region}-[a-z]$", var.zonal_location))
    error_message = "zonal_location must be a zone inside region, for example \"us-east1-b\"."
  }
}

variable "kubernetes_version" {
  type        = string
  description = "Minimum control plane version, for example \"1.33\". Null takes the release channel default. The channel still upgrades past this; it is a floor, not a pin."
  default     = null

  validation {
    condition     = var.kubernetes_version == null || can(regex("^1\\.[0-9]+(\\.[0-9]+(-gke\\.[0-9]+)?)?$", var.kubernetes_version))
    error_message = "kubernetes_version must look like \"1.33\", \"1.33.5\" or \"1.33.5-gke.1080000\"."
  }
}

# UNSPECIFIED is left out: it turns off auto-upgrade, and a cluster that never
# upgrades ages out of support and is then force-upgraded on Google's schedule.
variable "release_channel" {
  type        = string
  description = "GKE release channel. REGULAR is the default GKE picks for new clusters."
  default     = "REGULAR"

  validation {
    condition     = contains(["RAPID", "REGULAR", "STABLE", "EXTENDED"], var.release_channel)
    error_message = "release_channel must be RAPID, REGULAR, STABLE or EXTENDED."
  }
}

variable "deletion_protection" {
  type        = bool
  description = "Refuse to destroy the cluster. Set false and apply before a destroy."
  default     = true
}

# --- Networking --------------------------------------------------------------

variable "network_id" {
  type        = string
  description = "Network the cluster joins, as the vpc module's network_id or a self link"
}

variable "subnet_id" {
  type        = string
  description = "Subnet the nodes join, as the vpc module's subnet_id or a self link. It must carry the pod and service secondary ranges."
}

variable "pods_range_name" {
  type        = string
  description = "Name of the subnet's secondary range that pods draw addresses from"

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$", var.pods_range_name))
    error_message = "pods_range_name must be a secondary range name: 1-63 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "services_range_name" {
  type        = string
  description = "Name of the subnet's secondary range that Kubernetes services draw addresses from"

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$", var.services_range_name))
    error_message = "services_range_name must be a secondary range name: 1-63 lowercase letters, digits and hyphens, starting with a letter."
  }

  validation {
    condition     = var.services_range_name != var.pods_range_name
    error_message = "Pods and services need separate secondary ranges."
  }
}

# Nodes always reach the control plane privately, so, unlike the Azure module,
# restricting the public endpoint never cuts the cluster off from itself.
variable "private_endpoint_enabled" {
  type        = bool
  description = "Serve the API server on its private address only. Reaching it then needs a host inside the network, a VPN or Interconnect."
  default     = false
}

variable "master_authorized_networks" {
  type = list(object({
    cidr_block   = string
    display_name = optional(string)
  }))
  description = "CIDR ranges allowed to reach the API server. This is the analogue of the AWS module's cluster_endpoint_public_access_cidrs and the Azure module's api_server_authorized_ip_ranges."
  default     = []

  validation {
    condition     = alltrue([for n in var.master_authorized_networks : can(cidrhost(n.cidr_block, 0))])
    error_message = "Every cidr_block in master_authorized_networks must be a valid CIDR, for example \"203.0.113.0/24\"."
  }
}

# Leaving the control plane open has to be something a caller writes down, not
# something they get by not reading. The rule lives on this variable rather than
# on the two it reads, because validations that reference each other form a
# cycle Terraform rejects.
variable "allow_unrestricted_api_server_access" {
  type        = bool
  description = "Accept a public API server reachable from any address. Only for throwaway clusters; set master_authorized_networks or private_endpoint_enabled instead."
  default     = false

  validation {
    condition     = var.allow_unrestricted_api_server_access || var.private_endpoint_enabled || length(var.master_authorized_networks) > 0
    error_message = "A public API server with no authorized networks is reachable from every address on the internet. Set master_authorized_networks, or private_endpoint_enabled, or allow_unrestricted_api_server_access to record that the exposure is intended."
  }
}

# --- Node pools --------------------------------------------------------------

# Every key becomes a pool. The key is the pool name prefix, and GKE appends a
# 26-character suffix so a changed pool can be built before the old one goes.
variable "node_pools" {
  type = map(object({
    machine_type = optional(string, "n2-standard-8")
    min_count    = optional(number, 1)
    max_count    = optional(number, 5)
    disk_size_gb = optional(number, 100)
    disk_type    = optional(string, "pd-balanced")
    labels       = optional(map(string), {})
    taints = optional(list(object({
      key    = string
      value  = string
      effect = string
    })), [])
    node_locations = optional(list(string), [])
  }))
  description = "Node pools keyed by name. min_count and max_count count the whole pool, not each zone. The \"main\" key carries system workloads and must stay untainted."
  default = {
    main = {
      machine_type = "n2-standard-8"
      min_count    = 1
      max_count    = 5
      disk_size_gb = 100
    }
    # Onyx runs its document index in the cluster on GCP, because GCP has no
    # managed OpenSearch. The label and taint match the Azure module so one
    # set of chart values places the index on either cloud.
    index = {
      machine_type = "n2-highmem-4"
      min_count    = 1
      max_count    = 3
      disk_size_gb = 200
      labels       = { "onyx.app/workload" = "document-index" }
      taints       = [{ key = "document-index", value = "true", effect = "NO_SCHEDULE" }]
    }
  }

  validation {
    condition     = contains(keys(var.node_pools), "main")
    error_message = "node_pools must contain a \"main\" key for system workloads."
  }

  # The key is a name prefix. GKE caps a pool name at 40 characters and the
  # generated suffix takes 26 of them plus the joining hyphen.
  validation {
    condition     = alltrue([for k in keys(var.node_pools) : can(regex("^[a-z][a-z0-9]{0,12}$", k))])
    error_message = "Node pool keys must be 1-13 characters, start with a lowercase letter, and contain only lowercase letters and digits."
  }

  validation {
    condition     = alltrue([for p in var.node_pools : p.min_count >= 0 && p.max_count >= 1 && p.max_count >= p.min_count])
    error_message = "Every node pool needs min_count of 0 or more, max_count of 1 or more, and max_count greater than or equal to min_count."
  }

  validation {
    condition     = alltrue([for p in var.node_pools : p.disk_size_gb >= 10])
    error_message = "GKE needs a boot disk of at least 10 GiB."
  }

  validation {
    condition     = alltrue([for p in var.node_pools : contains(["pd-standard", "pd-balanced", "pd-ssd", "hyperdisk-balanced"], p.disk_type)])
    error_message = "disk_type must be pd-standard, pd-balanced, pd-ssd or hyperdisk-balanced."
  }

  validation {
    condition     = alltrue(flatten([for p in var.node_pools : [for t in p.taints : contains(["NO_SCHEDULE", "PREFER_NO_SCHEDULE", "NO_EXECUTE"], t.effect)]]))
    error_message = "Taint effects must be NO_SCHEDULE, PREFER_NO_SCHEDULE or NO_EXECUTE."
  }

  validation {
    condition     = alltrue(flatten([for p in var.node_pools : [for z in p.node_locations : can(regex("^${var.region}-[a-z]$", z))]]))
    error_message = "Every node_locations entry must be a zone inside region, for example \"us-east1-b\"."
  }

  # kube-dns, metrics-server and the other system pods tolerate no custom
  # taint, so a tainted main pool leaves them nowhere to run.
  validation {
    condition     = length(try(var.node_pools["main"].taints, [])) == 0
    error_message = "The \"main\" pool carries system workloads, which tolerate no custom taint. Move the workloads that need a taint to a pool of their own."
  }
}

variable "index_node_pool_enabled" {
  type        = bool
  description = "Create the document-index node pool. On by default, unlike the AWS module: GCP has no managed OpenSearch, so the index runs in the cluster."
  default     = true
}

# GKE surges one node at a time by default. Declaring it keeps a stray apply
# from changing how upgrades behave without anyone asking.
variable "node_pool_max_surge" {
  type        = number
  description = "Extra nodes GKE may add while upgrading a pool. The machine family's CPU quota has to cover the pool and the surge."
  default     = 1

  validation {
    condition     = var.node_pool_max_surge >= 0 && floor(var.node_pool_max_surge) == var.node_pool_max_surge
    error_message = "node_pool_max_surge must be a whole number of 0 or more."
  }
}

variable "enable_gpu_node_pool" {
  type        = bool
  description = "Create a tainted GPU pool for the embedding model server. GKE installs the driver and the device plugin, so nothing extra has to be deployed into the cluster."
  default     = false

  validation {
    condition     = !var.enable_gpu_node_pool || !contains(keys(var.node_pools), "gpu")
    error_message = "enable_gpu_node_pool adds a pool under the key \"gpu\", which node_pools already defines. Rename yours so the GPU pool does not replace it."
  }
}

variable "gpu_node_machine_type" {
  type        = string
  description = "Machine type for the GPU pool. It must match the accelerator: g2 carries L4, a2 carries A100, n1 takes T4."
  default     = "g2-standard-8"
}

variable "gpu_accelerator_type" {
  type        = string
  description = "GPU attached to each node. One NVIDIA L4 is enough for the embedding model."
  default     = "nvidia-l4"

  validation {
    condition     = can(regex("^nvidia-[a-z0-9-]+$", var.gpu_accelerator_type))
    error_message = "gpu_accelerator_type must be a GKE accelerator name such as \"nvidia-l4\" or \"nvidia-tesla-t4\"."
  }
}

variable "gpu_accelerator_count" {
  type        = number
  description = "GPUs per node"
  default     = 1

  validation {
    condition     = var.gpu_accelerator_count >= 1 && floor(var.gpu_accelerator_count) == var.gpu_accelerator_count
    error_message = "gpu_accelerator_count must be a whole number of 1 or more."
  }
}

variable "gpu_driver_version" {
  type        = string
  description = "Driver GKE installs on GPU nodes. INSTALLATION_DISABLED leaves it to a driver DaemonSet you deploy yourself."
  default     = "LATEST"

  validation {
    condition     = contains(["DEFAULT", "LATEST", "INSTALLATION_DISABLED"], var.gpu_driver_version)
    error_message = "gpu_driver_version must be DEFAULT, LATEST or INSTALLATION_DISABLED."
  }
}

# Not every zone in a region stocks every GPU. A regional pool asks for a node
# in each zone it spans, so a zone without the accelerator fails the pool.
variable "gpu_node_locations" {
  type        = list(string)
  description = "Zones for the GPU pool. Empty uses every zone of the cluster; list only zones that stock gpu_accelerator_type."
  default     = []

  validation {
    condition     = alltrue([for z in var.gpu_node_locations : can(regex("^${var.region}-[a-z]$", z))])
    error_message = "Every entry in gpu_node_locations must be a zone inside region, for example \"us-east1-b\"."
  }
}

variable "enable_sandbox_node_pool" {
  type        = bool
  description = "Create a tainted pool for Craft sandbox workloads"
  default     = false

  validation {
    condition     = !var.enable_sandbox_node_pool || !contains(keys(var.node_pools), "sandbox")
    error_message = "enable_sandbox_node_pool adds a pool under the key \"sandbox\", which node_pools already defines. Rename yours so the sandbox pool does not replace it."
  }
}

variable "sandbox_node_machine_type" {
  type        = string
  description = "Machine type for the Craft sandbox pool"
  default     = "n2-standard-8"
}

variable "sandbox_node_min_count" {
  type        = number
  description = "Minimum nodes in the Craft sandbox pool, across all its zones"
  default     = 1

  validation {
    condition     = var.sandbox_node_min_count >= 0
    error_message = "sandbox_node_min_count must be 0 or more."
  }
}

variable "sandbox_node_max_count" {
  type        = number
  description = "Maximum nodes in the Craft sandbox pool, across all its zones"
  default     = 7

  validation {
    condition     = var.sandbox_node_max_count >= 1 && var.sandbox_node_max_count >= var.sandbox_node_min_count
    error_message = "sandbox_node_max_count must be 1 or more and at least sandbox_node_min_count."
  }
}

variable "sandbox_node_disk_size_gb" {
  type        = number
  description = "Boot disk for Craft sandbox nodes. Size it so ephemeral storage is not what limits scheduling: each sandbox pod reserves about 5.5 GiB, so allow that per pod plus room for the image cache."
  default     = 200

  validation {
    condition     = var.sandbox_node_disk_size_gb >= 30
    error_message = "sandbox_node_disk_size_gb must be at least 30 GiB; the OS image and container cache leave too little ephemeral storage for even one sandbox pod below that."
  }
}

# Off by default. GKE taints a gVisor pool sandbox.gke.io/runtime=gvisor, and
# only pods with runtimeClassName: gvisor tolerate it. The chart's sandbox
# PodTemplate sets no runtime class, so turning this on without a chart change
# leaves every sandbox pod pending.
variable "sandbox_gvisor_enabled" {
  type        = bool
  description = "Run the sandbox pool under GKE Sandbox (gVisor). Needs sandbox pods to set runtimeClassName: gvisor, which the Onyx chart does not do yet."
  default     = false
}

# --- Workload identity -------------------------------------------------------
# GKE federates a Kubernetes service account straight to IAM, so there is no
# Google service account to impersonate. Grant roles to the
# workload_identity_principal output instead.

variable "workload_namespace" {
  type        = string
  description = "Namespace of the workload service account. The Helm release should install into it."
  default     = "onyx"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", var.workload_namespace))
    error_message = "workload_namespace must be a Kubernetes namespace name: 1-63 lowercase letters, digits and hyphens, starting and ending with a letter or digit."
  }
}

variable "workload_service_account_name" {
  type        = string
  description = "Kubernetes service account that IAM grants reach through workload identity. Point the chart's workloads at it."
  default     = "onyx-workload-access"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$", var.workload_service_account_name))
    error_message = "workload_service_account_name must be a Kubernetes name: lowercase letters, digits, hyphens and dots, starting and ending with a letter or digit."
  }
}

# A service account cannot be created before its namespace exists, and on a
# fresh cluster nothing has made it yet: the Helm release that would is
# installed after Terraform finishes.
variable "create_workload_namespace" {
  type        = bool
  description = "Create the namespace the workload service account lives in. Turn this off only when something else creates it before Terraform runs."
  default     = true
}

variable "create_workload_service_account" {
  type        = bool
  description = "Create the service account named by workload_service_account_name. Turn this off when the Helm chart already creates it; the principal output still names it."
  default     = true
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to the cluster and its node VMs"
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.labels : can(regex("^[a-z][a-z0-9_-]{0,62}$", k)) && can(regex("^[a-z0-9_-]{0,63}$", v))
    ])
    error_message = "Label keys must start with a lowercase letter; keys and values may only hold lowercase letters, digits, underscores and hyphens, up to 63 characters."
  }
}
