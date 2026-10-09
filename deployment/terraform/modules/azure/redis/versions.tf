terraform {
  required_version = ">= 1.12.0"

  required_providers {
    # 4.53 is the first release whose `clustering_policy` validation accepts
    # NoCluster, which is this module's default. 4.50 through 4.52 reject it at
    # plan time, and before 4.50 azurerm_managed_redis does not exist at all.
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.53"
    }
  }
}
