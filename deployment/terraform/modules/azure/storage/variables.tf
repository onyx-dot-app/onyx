variable "storage_account_name" {
  type        = string
  description = "Name of the storage account. Must be globally unique across Azure."

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "storage_account_name must be 3-24 characters of lowercase letters and digits only (Azure limit). Hyphens and uppercase are not allowed."
  }
}

variable "container_name" {
  type        = string
  description = "Blob container that holds the Onyx file store. Maps to AZURE_FILE_STORE_CONTAINER_NAME."
  default     = "onyx-file-store"

  # Azure rejects consecutive hyphens, and anything shorter than three
  # characters. The pattern allows at most one hyphen between runs of
  # alphanumerics, which is the rule Azure actually applies; the length check is
  # separate because folding 3-63 into the same expression obscures it.
  validation {
    condition = (
      length(var.container_name) >= 3 &&
      length(var.container_name) <= 63 &&
      can(regex("^[a-z0-9](-?[a-z0-9])+$", var.container_name))
    )
    error_message = "container_name must be 3-63 characters of lowercase letters, digits and single hyphens, must start and end with a letter or digit, and cannot contain consecutive hyphens."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the storage account"
}

variable "location" {
  type        = string
  description = "Azure region, for example \"eastus\""
}

variable "account_replication_type" {
  type        = string
  description = "Replication for the account. ZRS spreads copies across zones in one region, which is the closest match to how the AWS modules treat S3. LRS is cheaper but single-zone. Premium offers only LRS and ZRS."
  default     = "ZRS"

  validation {
    condition     = contains(["LRS", "ZRS", "GRS", "RAGRS", "GZRS", "RAGZRS"], var.account_replication_type)
    error_message = "account_replication_type must be one of: LRS, ZRS, GRS, RAGRS, GZRS, RAGZRS."
  }

  validation {
    condition     = var.account_tier != "Premium" || contains(["LRS", "ZRS"], var.account_replication_type)
    error_message = "Premium block blob accounts support only LRS and ZRS replication."
  }
}

variable "account_tier" {
  type        = string
  description = "Performance tier. Standard is correct for a document file store; Premium is for low-latency block blob workloads."
  default     = "Standard"

  validation {
    condition     = contains(["Standard", "Premium"], var.account_tier)
    error_message = "account_tier must be Standard or Premium."
  }
}

# Onyx authenticates to Blob with DefaultAzureCredential, so the account does
# not need shared keys. Leaving them off means a leaked key cannot exist.
variable "shared_access_key_enabled" {
  type        = bool
  description = "Allow authenticating with the account's shared keys. Off by default: Onyx uses workload identity, and callers that need a key can set AZURE_STORAGE_ACCOUNT_KEY only after turning this on. Set storage_use_azuread = true on the azurerm provider so Terraform itself does not reach for a key either."
  default     = false
}

variable "enable_versioning" {
  type        = bool
  description = "Keep previous versions of overwritten blobs"
  default     = true
}

variable "blob_soft_delete_days" {
  type        = number
  description = "Days a deleted blob stays recoverable. 0 disables soft delete."
  default     = 7

  validation {
    condition     = var.blob_soft_delete_days >= 0 && var.blob_soft_delete_days <= 365
    error_message = "blob_soft_delete_days must be between 0 (disabled) and 365 (Azure limit)."
  }
}

variable "container_soft_delete_days" {
  type        = number
  description = "Days a deleted container stays recoverable. 0 disables soft delete."
  default     = 7

  validation {
    condition     = var.container_soft_delete_days >= 0 && var.container_soft_delete_days <= 365
    error_message = "container_soft_delete_days must be between 0 (disabled) and 365 (Azure limit)."
  }
}

variable "noncurrent_expiration_days" {
  type        = number
  description = "Days to retain non-current blob versions. Only applies when enable_versioning is true."
  default     = 90

  validation {
    condition     = var.noncurrent_expiration_days > 0
    error_message = "noncurrent_expiration_days must be greater than 0."
  }
}

variable "expiration_days" {
  type        = number
  description = "Days after which current blobs are deleted. 0 disables expiry."
  default     = 0

  validation {
    condition     = var.expiration_days >= 0
    error_message = "expiration_days must be 0 (disabled) or a positive number of days."
  }
}

variable "transition_to_cool" {
  type        = bool
  description = "Move blobs to the Cool access tier once they stop being modified. Not available on Premium: block blob accounts have no Cool tier."
  default     = true

  validation {
    condition     = !var.transition_to_cool || var.account_tier != "Premium"
    error_message = "transition_to_cool is not available on Premium: block blob accounts have no Cool tier, and Azure rejects the lifecycle rule. Set transition_to_cool = false alongside account_tier = \"Premium\"."
  }
}

# Azure has no equivalent of S3 Intelligent-Tiering, so the AWS modules'
# 7-day transition does not carry over: Cool bills a minimum of 30 days per
# blob, and moving earlier costs more than it saves.
variable "transition_to_cool_days" {
  type        = number
  description = "Days since last modification before a blob moves to the Cool tier. Below 30 the early-deletion charge outweighs the storage saving."
  default     = 30

  validation {
    condition     = var.transition_to_cool_days >= 1
    error_message = "transition_to_cool_days must be at least 1."
  }
}

variable "allowed_subnet_ids" {
  type        = list(string)
  description = "Subnets allowed to reach the account. Each needs the Microsoft.Storage service endpoint. Leaving this and allowed_source_ips empty keeps the account reachable from any network and gated on Entra ID alone."
  default     = []
}

variable "allowed_source_ips" {
  type        = list(string)
  description = "Public IPv4 addresses or CIDR ranges allowed to reach the account."
  default     = []

  validation {
    condition     = alltrue([for ip in var.allowed_source_ips : !can(regex("/(3[12])$", ip))])
    error_message = "Azure rejects /31 and /32 in storage network rules. Write a single address without a prefix length."
  }
}

variable "network_rules_bypass" {
  type        = list(string)
  description = "Azure platform paths exempted from the network rules. AzureServices is what lets Monitor, Backup and the portal reach the account."
  default     = ["AzureServices"]

  validation {
    condition     = alltrue([for b in var.network_rules_bypass : contains(["AzureServices", "Logging", "Metrics", "None"], b)])
    error_message = "network_rules_bypass entries must be one of: AzureServices, Logging, Metrics, None."
  }

  validation {
    condition     = !contains(var.network_rules_bypass, "None") || length(var.network_rules_bypass) == 1
    error_message = "None means no exemptions at all, so it cannot be combined with AzureServices, Logging or Metrics."
  }
}

variable "public_network_access_enabled" {
  type        = bool
  description = "Allow the account's public endpoint to be reached at all. Set false only when every consumer goes through a private endpoint, otherwise the cluster loses access."
  default     = true
}

variable "min_tls_version" {
  type        = string
  description = "Minimum TLS version accepted by the account. Only TLS1_2 is accepted: Azure retired the older versions for storage."
  default     = "TLS1_2"

  validation {
    condition     = var.min_tls_version == "TLS1_2"
    error_message = "min_tls_version must be TLS1_2. Azure retired TLS 1.0 and 1.1 for storage, so the older values only produce a setting the platform will not honour."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to the storage account"
  default     = {}
}
