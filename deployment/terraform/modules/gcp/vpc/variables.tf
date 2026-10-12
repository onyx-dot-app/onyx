variable "name" {
  type        = string
  description = "Name prefix for the network and its resources"
  default     = "onyx"

  # Every resource name is "<name>-<suffix>" and GCP caps names at 63
  # characters (RFC 1035). The longest suffix is "-services", so 54 is the
  # most the prefix can take.
  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,52}[a-z0-9])?$", var.name))
    error_message = "name must be 1-54 characters of lowercase letters, digits and hyphens, start with a letter and not end with a hyphen."
  }
}

variable "project_id" {
  type        = string
  description = "GCP project that holds the network"

  validation {
    condition     = can(regex("^[a-z][-a-z0-9]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project ID: 6-30 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  type        = string
  description = "GCP region for the subnet, router and NAT, for example \"us-east1\""

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "region must be a GCP region such as \"us-east1\", not a zone."
  }
}

# Primary range for the nodes. GKE pods and services draw from the two
# secondary ranges below, so this only has to cover node IPs and internal
# load balancers.
variable "subnet_cidr" {
  type        = string
  description = "Primary IPv4 range of the subnet, used for node IPs"
  default     = "10.0.0.0/20"

  validation {
    condition     = can(cidrhost(var.subnet_cidr, 0)) && can(regex("^[0-9.]+/[0-9]+$", var.subnet_cidr)) && try(cidrsubnet(var.subnet_cidr, 0, 0) == var.subnet_cidr, false)
    error_message = "subnet_cidr must be an IPv4 CIDR whose address is the start of the range, e.g. \"10.0.0.0/20\"."
  }
}

# A /14 gives GKE room for about 1000 nodes at the default 110 pods per node,
# each node taking a /24 from this range.
variable "pods_cidr" {
  type        = string
  description = "Secondary range for GKE pod IPs"
  default     = "10.4.0.0/14"

  validation {
    condition     = can(cidrhost(var.pods_cidr, 0)) && can(regex("^[0-9.]+/[0-9]+$", var.pods_cidr)) && try(cidrsubnet(var.pods_cidr, 0, 0) == var.pods_cidr, false)
    error_message = "pods_cidr must be an IPv4 CIDR whose address is the start of the range, e.g. \"10.4.0.0/14\"."
  }
}

variable "services_cidr" {
  type        = string
  description = "Secondary range for GKE service (ClusterIP) IPs"
  default     = "10.8.0.0/20"

  validation {
    condition     = can(cidrhost(var.services_cidr, 0)) && can(regex("^[0-9.]+/[0-9]+$", var.services_cidr)) && try(cidrsubnet(var.services_cidr, 0, 0) == var.services_cidr, false)
    error_message = "services_cidr must be an IPv4 CIDR whose address is the start of the range, e.g. \"10.8.0.0/20\"."
  }
}

# Cloud SQL and Memorystore draw their private IPs from this range, which
# Google allocates from free RFC 1918 space in the network. /16 leaves room for
# every producer service that may peer in later; the range cannot be grown in
# place once the peering exists.
variable "psa_prefix_length" {
  type        = number
  description = "Prefix length of the range reserved for Private Service Access (Cloud SQL, Memorystore)"
  default     = 16

  validation {
    condition     = var.psa_prefix_length >= 8 && var.psa_prefix_length <= 24 && floor(var.psa_prefix_length) == var.psa_prefix_length
    error_message = "psa_prefix_length must be a whole number between 8 and 24. Cloud SQL needs at least a /24."
  }
}

variable "enable_flow_logs" {
  type        = bool
  description = "Write VPC flow logs for the subnet to Cloud Logging"
  default     = true
}

variable "flow_log_sampling" {
  type        = number
  description = "Fraction of flows to log, greater than 0 and at most 1. Flow logs are billed by volume."
  default     = 0.5

  validation {
    condition     = var.flow_log_sampling > 0 && var.flow_log_sampling <= 1
    error_message = "flow_log_sampling must be greater than 0 and at most 1. Set enable_flow_logs = false to turn flow logs off."
  }
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to every network resource that supports them"
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.labels : can(regex("^[a-z][a-z0-9_-]{0,62}$", k)) && can(regex("^[a-z0-9_-]{0,63}$", v))
    ])
    error_message = "Label keys must start with a lowercase letter; keys and values may only hold lowercase letters, digits, underscores and hyphens, up to 63 characters."
  }
}
