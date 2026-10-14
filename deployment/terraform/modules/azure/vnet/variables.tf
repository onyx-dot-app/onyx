variable "name" {
  type        = string
  description = "Name prefix for the virtual network and its resources"
  default     = "onyx"
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the virtual network"
}

variable "location" {
  type        = string
  description = "Azure region, for example \"eastus\""
}

variable "address_space" {
  type        = list(string)
  description = "Address space for the virtual network"
  default     = ["10.0.0.0/16"]
}

# Azure subnets are named resources, and delegation is a property of the subnet
# rather than of the database that uses it. A map keyed by purpose therefore
# replaces the AWS module's public/private CIDR lists. The defaults tile
# 10.0.0.0/16 and leave 10.0.19.0 onward free.
variable "subnets" {
  type = map(object({
    address_prefixes  = list(string)
    service_endpoints = optional(list(string), [])
    # Opt-in. Azure does not allow a NAT gateway on an Application Gateway
    # subnet, and a database subnet has no use for one, so a caller writing
    # their own map has to ask for egress rather than remember to refuse it.
    nat_gateway = optional(bool, false)
    # Service name to delegate the subnet to, for example
    # "Microsoft.DBforPostgreSQL/flexibleServers". Null leaves the subnet
    # undelegated.
    delegation         = optional(string)
    delegation_actions = optional(list(string), ["Microsoft.Network/virtualNetworks/subnets/join/action"])
    # "Disabled" is required on any subnet that holds a private endpoint.
    private_endpoint_network_policies = optional(string, "Disabled")
  }))
  description = "Subnets to create, keyed by purpose. Each key becomes a subnet named \"<name>-<key>\"."
  default = {
    # Node and pod addressing for AKS. The Microsoft.Storage service endpoint
    # is what lets the storage account restrict access to this subnet, the way
    # the S3 gateway endpoint does on AWS.
    aks = {
      address_prefixes  = ["10.0.0.0/20"]
      service_endpoints = ["Microsoft.Storage"]
      nat_gateway       = true
    }
    # Private endpoints for Redis and Blob storage.
    private_endpoints = {
      address_prefixes = ["10.0.16.0/24"]
    }
    # PostgreSQL Flexible Server requires a delegated subnet of its own and
    # does not need egress.
    postgres = {
      address_prefixes = ["10.0.17.0/24"]
      delegation       = "Microsoft.DBforPostgreSQL/flexibleServers"
    }
    # Application Gateway requires a dedicated subnet and does not support a
    # NAT gateway on it.
    app_gateway = {
      address_prefixes = ["10.0.18.0/24"]
    }
  }

  validation {
    condition     = alltrue([for s in var.subnets : contains(["Disabled", "Enabled", "NetworkSecurityGroupEnabled", "RouteTableEnabled"], s.private_endpoint_network_policies)])
    error_message = "private_endpoint_network_policies must be one of: Disabled, Enabled, NetworkSecurityGroupEnabled, RouteTableEnabled."
  }

  validation {
    condition     = alltrue([for s in var.subnets : length(s.address_prefixes) > 0])
    error_message = "Every subnet must declare at least one address prefix."
  }
}

variable "enable_nat_gateway" {
  type        = bool
  description = "Provision a NAT gateway and attach it to every subnet whose nat_gateway flag is true. Gives the cluster a stable egress IP, which is what allowlists on downstream systems key off."
  default     = true
}

variable "nat_gateway_zones" {
  type        = list(string)
  description = "Availability zones for the NAT gateway and its public IP. Empty is regional (no zone), which survives a single-zone outage. Pinning a zone is cheaper to reason about but makes egress a single-zone dependency."
  default     = []

  validation {
    condition     = length(var.nat_gateway_zones) <= 1
    error_message = "A NAT gateway is either regional (empty list) or pinned to exactly one zone."
  }
}

variable "nat_gateway_idle_timeout_minutes" {
  type        = number
  description = "Idle timeout for NAT gateway flows, in minutes"
  default     = 10

  validation {
    condition     = var.nat_gateway_idle_timeout_minutes >= 4 && var.nat_gateway_idle_timeout_minutes <= 120
    error_message = "nat_gateway_idle_timeout_minutes must be between 4 and 120 (Azure limit)."
  }
}

# Flow logs are opt-in here, unlike the AWS module where they are on by default.
# Azure writes them to a storage account rather than to a log service, and needs
# a Network Watcher in the region. Turning them on by default would mean either
# creating a storage account the caller did not ask for, or failing on
# subscriptions where Network Watcher was never provisioned.
variable "enable_flow_logs" {
  type        = bool
  description = "Send virtual network flow logs to a storage account. Requires flow_log_storage_account_id and a Network Watcher in this region."
  default     = false

  validation {
    condition     = !var.enable_flow_logs || var.flow_log_storage_account_id != null
    error_message = "flow_log_storage_account_id must be set when enable_flow_logs is true."
  }

  # The flow log resource needs both a destination and a watcher. Checking only
  # the destination would let a plan through that fails at apply.
  validation {
    condition     = !var.enable_flow_logs || try(trimspace(var.network_watcher_name), "") != ""
    error_message = "network_watcher_name must be set to a non-blank value when enable_flow_logs is true. Azure names the one it creates automatically \"NetworkWatcher_<region>\"."
  }
}

variable "flow_log_storage_account_id" {
  type        = string
  description = "Storage account that receives flow logs. Use an account dedicated to logs, not the one holding application data."
  default     = null
}

variable "flow_log_retention_days" {
  type        = number
  description = "Days to retain flow logs, 0 to retain them forever. Azure caps this at 365, so the twelve-month log-retention control is met exactly rather than with the 30-day buffer the AWS modules use."
  default     = 365

  validation {
    condition     = var.flow_log_retention_days >= 0 && var.flow_log_retention_days <= 365
    error_message = "flow_log_retention_days must be between 0 (retain forever) and 365 (Azure limit)."
  }
}

variable "network_watcher_name" {
  type        = string
  description = "Network Watcher that owns the flow log. Azure names the one it creates automatically \"NetworkWatcher_<region>\"."
  default     = null
}

variable "network_watcher_resource_group_name" {
  type        = string
  description = "Resource group holding the Network Watcher. Azure creates its own in \"NetworkWatcherRG\"."
  default     = "NetworkWatcherRG"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to all network resources"
  default     = {}
}
