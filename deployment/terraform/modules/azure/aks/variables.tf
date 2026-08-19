variable "cluster_name" {
  type        = string
  description = "Name of the cluster"
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the cluster"
}

variable "location" {
  type        = string
  description = "Azure region, for example \"eastus\""
}

variable "kubernetes_version" {
  type        = string
  description = "Kubernetes version for the control plane. Move one minor at a time."
  default     = "1.33"
}

variable "subnet_id" {
  type        = string
  description = "Subnet the nodes join"
}

variable "sku_tier" {
  type        = string
  description = "Control plane tier. Free carries no uptime SLA; Standard does. Premium adds long-term support."
  default     = "Standard"

  validation {
    condition     = contains(["Free", "Standard", "Premium"], var.sku_tier)
    error_message = "sku_tier must be Free, Standard or Premium."
  }
}

variable "private_cluster_enabled" {
  type        = bool
  description = "Give the API server a private endpoint only. Reaching it then needs a host inside the network, a VPN or Azure Bastion."
  default     = false

  validation {
    condition     = !var.private_cluster_enabled || length(var.api_server_authorized_ip_ranges) == 0
    error_message = "api_server_authorized_ip_ranges only applies to a public API server, so it cannot be combined with private_cluster_enabled."
  }
}

variable "api_server_authorized_ip_ranges" {
  type        = list(string)
  description = "CIDR ranges allowed to reach the public API server. This is the analogue of the AWS module's cluster_endpoint_public_access_cidrs."
  default     = []
}

# Leaving the control plane open has to be something a caller writes down, not
# something they get by not reading. The rule lives on this variable rather than
# on the two it reads, because validations that reference each other form a
# cycle Terraform rejects.
variable "allow_unrestricted_api_server_access" {
  type        = bool
  description = "Accept a public API server reachable from any address. Only for throwaway clusters; set api_server_authorized_ip_ranges or private_cluster_enabled instead."
  default     = false

  validation {
    condition     = var.allow_unrestricted_api_server_access || var.private_cluster_enabled || length(var.api_server_authorized_ip_ranges) > 0
    error_message = "A public API server with no authorized ranges is reachable from every address on the internet. Set api_server_authorized_ip_ranges, or private_cluster_enabled, or allow_unrestricted_api_server_access to record that the exposure is intended."
  }
}

# --- Networking --------------------------------------------------------------

variable "network_plugin_mode" {
  type        = string
  description = "Overlay gives pods addresses from pod_cidr rather than from the subnet, so the subnet only has to be large enough for nodes. Null puts pod addresses in the subnet, which needs a much larger one."
  default     = "overlay"

  validation {
    condition     = var.network_plugin_mode == null || var.network_plugin_mode == "overlay"
    error_message = "network_plugin_mode must be \"overlay\" or null."
  }
}

variable "pod_cidr" {
  type        = string
  description = "Address range pods draw from in overlay mode. Must not overlap the virtual network."
  default     = "192.168.0.0/16"
}

variable "service_cidr" {
  type        = string
  description = "Address range for Kubernetes service IPs. Must not overlap the virtual network or pod_cidr."
  default     = "172.16.0.0/16"
}

variable "dns_service_ip" {
  type        = string
  description = "Address of the in-cluster DNS service. Null takes the tenth address of service_cidr, which is what removes the chance of setting one outside it."
  default     = null
}

# Off by default for the same reason as the AWS module: a cluster that has
# carried inert NetworkPolicies picks up enforcement the moment this is turned
# on, and whatever those policies say takes effect at once.
variable "network_policy" {
  type        = string
  description = "NetworkPolicy engine. Null leaves existing policies inert. Cilium is the current recommendation and needs overlay mode."
  default     = null

  validation {
    condition     = var.network_policy == null || contains(["azure", "calico", "cilium"], var.network_policy)
    error_message = "network_policy must be one of: azure, calico, cilium, or null to leave enforcement off."
  }

  validation {
    condition     = var.network_policy != "cilium" || var.network_plugin_mode == "overlay"
    error_message = "The cilium data plane requires network_plugin_mode = \"overlay\"."
  }
}

# The vnet module attaches a NAT gateway to the node subnet so egress keeps one
# address. Taking that path means AKS must not manage outbound itself.
variable "outbound_type" {
  type        = string
  description = "How nodes reach the internet. userAssignedNATGateway uses the NAT gateway already on the subnet and keeps egress on a stable address. loadBalancer lets AKS manage it, and the addresses can change."
  default     = "userAssignedNATGateway"

  validation {
    condition     = contains(["loadBalancer", "userAssignedNATGateway", "userDefinedRouting", "managedNATGateway"], var.outbound_type)
    error_message = "outbound_type must be one of: loadBalancer, userAssignedNATGateway, userDefinedRouting, managedNATGateway."
  }
}

# --- Node pools --------------------------------------------------------------

# The "main" pool becomes the cluster's system pool, which AKS requires inline
# and will not let you delete. Every other key becomes a pool of its own.
variable "node_pools" {
  type = map(object({
    vm_size         = optional(string, "Standard_D8ds_v5")
    min_count       = optional(number, 1)
    max_count       = optional(number, 5)
    os_disk_size_gb = optional(number, 100)
    os_disk_type    = optional(string, "Managed")
    node_labels     = optional(map(string), {})
    node_taints     = optional(list(string), [])
    zones           = optional(list(string), [])
    mode            = optional(string, "User")
  }))
  description = "Node pools keyed by name. The \"main\" key is the system pool."
  default = {
    main = {
      vm_size   = "Standard_D8ds_v5"
      min_count = 1
      max_count = 5
    }
    # Onyx runs its document index in-cluster on Azure, because Azure has no
    # managed OpenSearch. This pool is the one the index lands on.
    index = {
      vm_size         = "Standard_E8ds_v5"
      min_count       = 1
      max_count       = 1
      os_disk_size_gb = 512
      node_labels     = { "onyx.app/workload" = "document-index" }
      node_taints     = ["document-index=true:NoSchedule"]
    }
  }

  validation {
    condition     = contains(keys(var.node_pools), "main")
    error_message = "node_pools must contain a \"main\" key; AKS requires a system pool and will not let it be removed."
  }

  validation {
    condition     = alltrue([for k in keys(var.node_pools) : can(regex("^[a-z][a-z0-9]{0,11}$", k))])
    error_message = "Node pool names must be 1-12 characters, start with a lowercase letter, and contain only lowercase letters and digits (Azure limit)."
  }

  validation {
    condition     = alltrue([for p in var.node_pools : p.max_count >= p.min_count])
    error_message = "Every node pool needs max_count greater than or equal to min_count."
  }

  validation {
    condition     = length(try(var.node_pools["main"].node_taints, [])) == 0
    error_message = "The \"main\" pool becomes the cluster's system pool, and AKS accepts no taints on it. Move the workloads that need a taint to a pool of their own."
  }

  # A pool named the same as another pool's rotation name would break the
  # rotation. The injected gpu and sandbox keys are always considered, so the
  # answer does not change with the flags that enable them.
  validation {
    condition = length(setintersection(
      toset(concat(keys(var.node_pools), ["gpu", "sandbox"])),
      toset([for k in concat(keys(var.node_pools), ["gpu", "sandbox"]) : substr("${substr(k, 0, 6)}${substr(sha1(k), 0, 6)}", 0, 12)]),
    )) == 0
    error_message = "A node pool is named the same as another pool's generated rotation name, which would break rotation for that pool. Rename it."
  }
}

variable "index_node_pool_enabled" {
  type        = bool
  description = "Create the document-index node pool. On by default, unlike the AWS module: Azure has no managed OpenSearch, so the index runs in the cluster."
  default     = true
}

variable "enable_gpu_node_pool" {
  type        = bool
  description = "Create a tainted GPU pool for the embedding model server. AKS installs the driver and the device plugin itself, so nothing extra has to be deployed into the cluster."
  default     = false

  validation {
    condition     = !var.enable_gpu_node_pool || !contains(keys(var.node_pools), "gpu")
    error_message = "enable_gpu_node_pool adds a pool under the key \"gpu\", which node_pools already defines. Rename yours so the GPU pool does not replace it."
  }
}

variable "gpu_node_vm_size" {
  type        = string
  description = "VM size for the GPU pool. Standard_NC4as_T4_v3 carries one NVIDIA T4, which is enough for the embedding model."
  default     = "Standard_NC4as_T4_v3"
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

variable "sandbox_node_vm_size" {
  type        = string
  description = "VM size for the Craft sandbox pool"
  default     = "Standard_D8ds_v5"
}

variable "sandbox_node_min_count" {
  type        = number
  description = "Minimum nodes in the Craft sandbox pool"
  default     = 1
}

variable "sandbox_node_max_count" {
  type        = number
  description = "Maximum nodes in the Craft sandbox pool"
  default     = 7
}

variable "sandbox_node_disk_size_gb" {
  type        = number
  description = "OS disk for Craft sandbox nodes. Size it so ephemeral storage is not what limits scheduling: each sandbox pod reserves about 5.5 GiB, so allow that per pod plus room for the image cache."
  default     = 200

  validation {
    condition     = var.sandbox_node_disk_size_gb >= 30
    error_message = "sandbox_node_disk_size_gb must be at least 30 GiB; the OS image and container cache leave too little ephemeral storage for even one sandbox pod below that."
  }
}

# --- Workload identity -------------------------------------------------------
# Azure federates a managed identity to a Kubernetes service account rather
# than assuming a role from an OIDC subject, so this is the shape IRSA takes
# here. The cluster's OIDC issuer is the trust anchor either way.

variable "storage_account_ids" {
  type        = list(string)
  description = "Storage accounts the workload identity may read and write. Empty creates no identity, no role assignment and no service account."
  default     = []
}

variable "storage_role_definition_name" {
  type        = string
  description = "Built-in role granted on each storage account. Storage Blob Data Contributor covers reading, writing and deleting blobs, and nothing else."
  default     = "Storage Blob Data Contributor"
}

variable "workload_service_account_namespace" {
  type        = string
  description = "Namespace of the service account the workload identity federates to"
  default     = "onyx"
}

variable "workload_service_account_name" {
  type        = string
  description = "Service account the workload identity federates to. The module creates it, annotated with the identity's client id."
  default     = "onyx-workload-access"
}

variable "additional_workload_service_account_names" {
  type        = list(string)
  description = "Further service accounts in the same namespace that may use the identity. Use this for chart-created workloads such as <release>-sandbox-proxy. The module federates them but does not create them."
  default     = []
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
  description = "Create the service account named by workload_service_account_name. Turn this off when the Helm chart already creates it, and the module will only federate the identity to it."
  default     = true
}

# --- Cluster add-ons ---------------------------------------------------------

variable "create_premium_storage_class" {
  type        = bool
  description = "Create a Premium SSD storage class that binds on first use and can be expanded"
  default     = true
}

variable "premium_storage_class_name" {
  type        = string
  description = "Name of the storage class the module creates"
  default     = "onyx-premium"
}

# AKS already ships a class marked default, so marking a second one leaves the
# cluster with two and Kubernetes picks between them unpredictably. Take the
# existing default out of the running before turning this on.
variable "premium_storage_class_is_default" {
  type        = bool
  description = "Mark the created storage class as the cluster default. Only safe once the class AKS ships has had its default annotation removed."
  default     = false
}

variable "azure_policy_enabled" {
  type        = bool
  description = "Run the Azure Policy add-on, which reports and can enforce policy on cluster resources"
  default     = false
}

variable "log_analytics_workspace_id" {
  type        = string
  description = "Workspace that receives control plane logs and container insights. Null sends neither."
  default     = null
}

# Retention lives on the workspace here, not on the setting, which is why there
# is no retention variable to match the AWS module's.
variable "control_plane_log_categories" {
  type        = list(string)
  description = "Control plane log categories to send to the workspace"
  default     = ["kube-apiserver", "kube-audit", "kube-controller-manager", "kube-scheduler", "cluster-autoscaler"]

  validation {
    condition = alltrue([for c in var.control_plane_log_categories : contains([
      "kube-apiserver", "kube-audit", "kube-audit-admin", "kube-controller-manager",
      "kube-scheduler", "cluster-autoscaler", "cloud-controller-manager", "guard", "csi-azuredisk-controller",
      "csi-azurefile-controller", "csi-snapshot-controller",
    ], c)])
    error_message = "Each entry must be a category AKS publishes, such as kube-apiserver, kube-audit, kube-controller-manager, kube-scheduler or cluster-autoscaler."
  }
}

variable "entra_rbac_admin_group_object_ids" {
  type        = list(string)
  description = "Entra ID groups granted cluster admin. Empty leaves Kubernetes RBAC on its own with local accounts."
  default     = []
}

variable "entra_rbac_enabled" {
  type        = bool
  description = "Authorise Kubernetes actions through Azure RBAC rather than only through Kubernetes RBAC. Needs entra_rbac_admin_group_object_ids."
  default     = false

  validation {
    condition     = !var.entra_rbac_enabled || length(var.entra_rbac_admin_group_object_ids) > 0
    error_message = "entra_rbac_enabled needs at least one group in entra_rbac_admin_group_object_ids, otherwise nobody can administer the cluster."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to the cluster and its pools"
  default     = {}
}
