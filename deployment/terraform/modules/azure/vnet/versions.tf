terraform {
  required_version = ">= 1.12.0"

  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
      # Virtual network flow logs need azurerm_network_watcher_flow_log's
      # target_resource_id, which landed in 4.11.0: 4.10.0 does not have the
      # field and rejects the resource before planning.
      version = ">= 4.11.0, < 5.0"
    }
  }
}
