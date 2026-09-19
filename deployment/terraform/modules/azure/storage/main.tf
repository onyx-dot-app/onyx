locals {
  # With no allowlist the account stays reachable from any network and access
  # is gated on Entra ID alone, which is how the AWS s3 module behaves when no
  # bucket policy is set. Supplying either list flips the account to deny-first.
  restrict_network = length(var.allowed_subnet_ids) > 0 || length(var.allowed_source_ips) > 0

  # A management policy with no rules is rejected, so only create one when at
  # least one rule applies.
  has_lifecycle_rules = var.enable_versioning || var.expiration_days > 0 || var.transition_to_cool
}

resource "azurerm_storage_account" "this" {
  name                = var.storage_account_name
  resource_group_name = var.resource_group_name
  location            = var.location

  # Premium block blob is its own account kind. Leaving this at StorageV2 makes
  # Azure reject the account outright when the caller asks for Premium.
  account_kind             = var.account_tier == "Premium" ? "BlockBlobStorage" : "StorageV2"
  account_tier             = var.account_tier
  account_replication_type = var.account_replication_type

  https_traffic_only_enabled    = true
  min_tls_version               = var.min_tls_version
  public_network_access_enabled = var.public_network_access_enabled
  shared_access_key_enabled     = var.shared_access_key_enabled

  # The pair of settings that keep blobs from ever being served anonymously.
  allow_nested_items_to_be_public = false
  default_to_oauth_authentication = true

  tags = var.tags

  blob_properties {
    versioning_enabled = var.enable_versioning

    dynamic "delete_retention_policy" {
      for_each = var.blob_soft_delete_days > 0 ? [1] : []
      content {
        days = var.blob_soft_delete_days
      }
    }

    dynamic "container_delete_retention_policy" {
      for_each = var.container_soft_delete_days > 0 ? [1] : []
      content {
        days = var.container_soft_delete_days
      }
    }
  }

  dynamic "network_rules" {
    for_each = local.restrict_network ? [1] : []
    content {
      default_action             = "Deny"
      bypass                     = var.network_rules_bypass
      virtual_network_subnet_ids = var.allowed_subnet_ids
      ip_rules                   = var.allowed_source_ips
    }
  }
}

resource "azurerm_storage_container" "this" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "this" {
  count              = local.has_lifecycle_rules ? 1 : 0
  storage_account_id = azurerm_storage_account.this.id

  dynamic "rule" {
    for_each = var.enable_versioning ? [1] : []
    content {
      name    = "noncurrent-version-expiration"
      enabled = true

      filters {
        blob_types = ["blockBlob"]
      }

      actions {
        version {
          delete_after_days_since_creation = var.noncurrent_expiration_days
        }
      }
    }
  }

  dynamic "rule" {
    for_each = var.expiration_days > 0 ? [1] : []
    content {
      name    = "object-expiration"
      enabled = true

      filters {
        blob_types = ["blockBlob"]
      }

      actions {
        base_blob {
          delete_after_days_since_modification_greater_than = var.expiration_days
        }
      }
    }
  }

  dynamic "rule" {
    for_each = var.transition_to_cool ? [1] : []
    content {
      name    = "transition-to-cool"
      enabled = true

      filters {
        blob_types = ["blockBlob"]
      }

      actions {
        base_blob {
          tier_to_cool_after_days_since_modification_greater_than = var.transition_to_cool_days
        }
      }
    }
  }
}
