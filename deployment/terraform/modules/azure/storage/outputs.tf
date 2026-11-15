output "storage_account_id" {
  description = "Resource ID of the storage account. Role assignments and flow log destinations take this."
  value       = azurerm_storage_account.this.id
}

output "storage_account_name" {
  description = "Name of the storage account. Set this as AZURE_STORAGE_ACCOUNT_NAME."
  value       = azurerm_storage_account.this.name
}

output "primary_blob_endpoint" {
  description = "Blob service endpoint. Set this as AZURE_STORAGE_ACCOUNT_URL."
  value       = azurerm_storage_account.this.primary_blob_endpoint
}

output "container_name" {
  description = "Name of the file store container. Set this as AZURE_FILE_STORE_CONTAINER_NAME."
  value       = azurerm_storage_container.this.name
}

output "primary_access_key" {
  description = "Shared access key, null unless shared_access_key_enabled is true. Onyx uses workload identity and does not need it."
  value       = var.shared_access_key_enabled ? azurerm_storage_account.this.primary_access_key : null
  sensitive   = true
}

output "key_vault_key_id" {
  description = "Versionless ID of the customer-managed key. Null unless create_customer_managed_key is true."
  value       = var.create_customer_managed_key ? azurerm_key_vault_key.cmk[0].versionless_id : null
}

output "key_vault_id" {
  description = "Resource ID of the Key Vault that holds the customer-managed key. Null unless create_customer_managed_key is true."
  value       = var.create_customer_managed_key ? azurerm_key_vault.cmk[0].id : null
}
