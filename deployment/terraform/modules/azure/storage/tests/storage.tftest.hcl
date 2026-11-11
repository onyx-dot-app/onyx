# Plans the module against a mocked provider, so these run without an Azure
# subscription or credentials. Run with `terraform test` from the module directory.

mock_provider "azurerm" {
  # Key Vault access policies validate these as UUIDs.
  override_data {
    target = data.azurerm_client_config.current
    values = {
      tenant_id = "00000000-0000-0000-0000-000000000001"
      object_id = "00000000-0000-0000-0000-000000000002"
    }
  }

  override_resource {
    target = azurerm_user_assigned_identity.cmk
    values = {
      tenant_id    = "00000000-0000-0000-0000-000000000001"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }
}

variables {
  storage_account_name = "onyxfilestoreprod"
  resource_group_name  = "onyx-rg"
  location             = "eastus"
}

run "defaults_are_private_and_keyless" {
  command = plan

  assert {
    condition     = azurerm_storage_account.this.shared_access_key_enabled == false
    error_message = "Onyx authenticates with workload identity, so shared keys should be off by default."
  }

  assert {
    condition     = azurerm_storage_account.this.allow_nested_items_to_be_public == false
    error_message = "Blobs must never be servable anonymously."
  }

  assert {
    condition     = azurerm_storage_account.this.default_to_oauth_authentication == true
    error_message = "The account should default to Entra ID authentication."
  }

  assert {
    condition     = azurerm_storage_container.this.container_access_type == "private"
    error_message = "The file store container must be private."
  }

  assert {
    condition     = azurerm_storage_account.this.min_tls_version == "TLS1_2"
    error_message = "The account should refuse TLS below 1.2."
  }
}

run "no_allowlist_leaves_the_account_open_to_the_network" {
  command = plan

  assert {
    condition     = length(azurerm_storage_account.this.network_rules) == 0
    error_message = "With no allowlist the account is gated on Entra ID alone, matching how the AWS s3 module behaves with no bucket policy."
  }
}

run "an_allowlist_flips_the_account_to_deny_first" {
  command = plan

  variables {
    allowed_subnet_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet/subnets/onyx-aks"]
  }

  assert {
    condition     = one(azurerm_storage_account.this.network_rules).default_action == "Deny"
    error_message = "Supplying an allowlist must deny everything else."
  }

  assert {
    condition     = contains(one(azurerm_storage_account.this.network_rules).bypass, "AzureServices")
    error_message = "AzureServices must stay exempt or Monitor and Backup lose access."
  }
}

run "default_lifecycle_rules" {
  command = plan

  assert {
    condition     = length(azurerm_storage_management_policy.this[0].rule) == 2
    error_message = "Versioning and cool-tiering are on by default; blob expiry is not."
  }

  assert {
    condition     = contains(azurerm_storage_management_policy.this[0].rule[*].name, "noncurrent-version-expiration")
    error_message = "Non-current versions should expire by default."
  }

  assert {
    condition     = contains(azurerm_storage_management_policy.this[0].rule[*].name, "transition-to-cool")
    error_message = "Blobs should tier to Cool by default."
  }
}

run "expiry_adds_a_third_rule" {
  command = plan

  variables {
    expiration_days = 365
  }

  assert {
    condition     = length(azurerm_storage_management_policy.this[0].rule) == 3
    error_message = "Setting expiration_days should add the object-expiration rule."
  }
}

run "no_rules_means_no_policy" {
  command = plan

  variables {
    enable_versioning  = false
    transition_to_cool = false
    expiration_days    = 0
  }

  assert {
    condition     = length(azurerm_storage_management_policy.this) == 0
    error_message = "Azure rejects a management policy with no rules, so the module must not create one."
  }
}

run "premium_uses_the_account_kind_azure_requires" {
  command = plan

  variables {
    account_tier             = "Premium"
    account_replication_type = "ZRS"
    transition_to_cool       = false
  }

  assert {
    condition     = azurerm_storage_account.this.account_kind == "BlockBlobStorage"
    error_message = "Premium block blob is its own account kind; StorageV2 would be rejected outright."
  }
}

run "standard_stays_on_storage_v2" {
  command = plan

  assert {
    condition     = azurerm_storage_account.this.account_kind == "StorageV2"
    error_message = "Standard accounts should stay on StorageV2."
  }
}

run "rejects_premium_with_replication_it_cannot_have" {
  command = plan

  variables {
    account_tier             = "Premium"
    account_replication_type = "GRS"
    transition_to_cool       = false
  }

  expect_failures = [var.account_replication_type]
}

run "rejects_cool_tiering_on_premium" {
  command = plan

  # Premium block blob accounts have no Cool tier, so the rule Azure would
  # receive is one it rejects.
  variables {
    account_tier             = "Premium"
    account_replication_type = "ZRS"
  }

  expect_failures = [var.transition_to_cool]
}

run "rejects_a_bypass_of_none_alongside_anything_else" {
  command = plan

  variables {
    network_rules_bypass = ["None", "AzureServices"]
  }

  expect_failures = [var.network_rules_bypass]
}

run "accepts_a_bypass_of_none_on_its_own" {
  command = plan

  variables {
    network_rules_bypass = ["None"]
    allowed_subnet_ids   = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/onyx-rg/providers/Microsoft.Network/virtualNetworks/onyx-vnet/subnets/onyx-aks"]
  }

  assert {
    condition     = contains(one(azurerm_storage_account.this.network_rules).bypass, "None")
    error_message = "None on its own is a valid way to exempt nothing."
  }
}

run "rejects_consecutive_hyphens_in_the_container_name" {
  command = plan

  variables {
    container_name = "onyx--file-store"
  }

  expect_failures = [var.container_name]
}

run "rejects_a_container_name_that_is_too_short" {
  command = plan

  variables {
    container_name = "ab"
  }

  expect_failures = [var.container_name]
}

run "rejects_a_container_name_ending_in_a_hyphen" {
  command = plan

  variables {
    container_name = "onyx-file-store-"
  }

  expect_failures = [var.container_name]
}

run "rejects_a_retired_tls_version" {
  command = plan

  variables {
    min_tls_version = "TLS1_0"
  }

  expect_failures = [var.min_tls_version]
}

run "rejects_a_name_azure_would_reject" {
  command = plan

  variables {
    storage_account_name = "Onyx-File-Store"
  }

  expect_failures = [var.storage_account_name]
}

run "rejects_a_name_that_is_too_long" {
  command = plan

  variables {
    storage_account_name = "onyxfilestoreproductioneastus"
  }

  expect_failures = [var.storage_account_name]
}

run "rejects_a_host_prefix_azure_would_reject" {
  command = plan

  variables {
    allowed_source_ips = ["203.0.113.7/32"]
  }

  expect_failures = [var.allowed_source_ips]
}

run "rejects_an_invalid_bypass" {
  command = plan

  variables {
    network_rules_bypass = ["AzureServices", "Everything"]
  }

  expect_failures = [var.network_rules_bypass]
}

run "defaults_use_microsoft_managed_keys" {
  command = plan

  assert {
    condition = (
      length(azurerm_key_vault.cmk) == 0 &&
      length(azurerm_key_vault_key.cmk) == 0 &&
      length(azurerm_user_assigned_identity.cmk) == 0
    )
    error_message = "No Key Vault, key or identity should exist unless create_customer_managed_key is set."
  }

  assert {
    condition     = length(azurerm_storage_account.this.customer_managed_key) == 0 && length(azurerm_storage_account.this.identity) == 0
    error_message = "Existing accounts must see no encryption or identity change by default."
  }
}

run "a_customer_managed_key_encrypts_and_expires_the_account" {
  command = plan

  variables {
    storage_account_name        = "onyxsandboxarchive"
    container_name              = "sandbox-archives"
    create_customer_managed_key = true
    expiration_days             = 30
    noncurrent_expiration_days  = 7
    transition_to_cool          = false
  }

  assert {
    condition     = azurerm_key_vault.cmk[0].purge_protection_enabled == true
    error_message = "Azure storage needs purge protection on the key's vault."
  }

  assert {
    condition     = azurerm_key_vault.cmk[0].name == "kv-onyxsandboxar${substr(sha1("onyxsandboxarchive"), 0, 8)}"
    error_message = "The vault name should be kv- plus 13 characters of the account name plus an 8-character digest of it."
  }

  assert {
    condition     = toset(azurerm_key_vault.cmk[0].access_policy[1].key_permissions) == toset(["Get", "UnwrapKey", "WrapKey"])
    error_message = "The storage identity may only wrap and unwrap."
  }

  assert {
    condition     = one(azurerm_key_vault_key.cmk[0].rotation_policy[0].automatic).time_after_creation == "P90D"
    error_message = "The key should rotate every 90 days by default."
  }

  assert {
    condition     = length(azurerm_storage_account.this.customer_managed_key) == 1
    error_message = "The account should encrypt with the customer-managed key."
  }

  assert {
    condition     = one(azurerm_storage_account.this.identity).type == "UserAssigned"
    error_message = "The account reaches the key through a user-assigned identity."
  }

  assert {
    condition     = azurerm_storage_account.this.allow_nested_items_to_be_public == false && azurerm_storage_container.this.container_access_type == "private"
    error_message = "The archive must never be servable anonymously."
  }

  assert {
    condition     = one(azurerm_storage_account.this.blob_properties).versioning_enabled == true
    error_message = "Versioning must be on."
  }

  assert {
    condition     = one([for r in azurerm_storage_management_policy.this[0].rule : r if r.name == "object-expiration"]).actions[0].base_blob[0].delete_after_days_since_modification_greater_than == 30
    error_message = "Blobs should be deleted after expiration_days."
  }

  assert {
    condition     = one([for r in azurerm_storage_management_policy.this[0].rule : r if r.name == "noncurrent-version-expiration"]).actions[0].version[0].delete_after_days_since_creation == 7
    error_message = "Old versions should be deleted after noncurrent_expiration_days."
  }
}

run "rejects_a_malformed_key_vault_name" {
  command = plan

  variables {
    create_customer_managed_key = true
    key_vault_name              = "1-bad--name"
  }

  expect_failures = [var.key_vault_name]
}

run "a_long_account_name_keeps_the_full_vault_digest" {
  command = plan

  variables {
    storage_account_name        = "onyxenterpriseprodarc123"
    create_customer_managed_key = true
  }

  assert {
    condition = (
      length(azurerm_key_vault.cmk[0].name) <= 24 &&
      endswith(azurerm_key_vault.cmk[0].name, substr(sha1("onyxenterpriseprodarc123"), 0, 8))
    )
    error_message = "A 24-character account name must still give a vault name of at most 24 characters that ends in the full digest."
  }
}

run "rejects_a_key_vault_name_that_is_too_short" {
  command = plan

  variables {
    create_customer_managed_key = true
    key_vault_name              = "ab"
  }

  expect_failures = [var.key_vault_name]
}
