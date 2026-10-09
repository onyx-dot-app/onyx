output "policy_id" {
  description = "Resource ID of the WAF policy. Attach it to an Application Gateway. Front Door uses a different resource, azurerm_cdn_frontdoor_firewall_policy, and cannot take this one."
  value       = azurerm_web_application_firewall_policy.this.id
}

output "policy_name" {
  description = "Name of the WAF policy"
  value       = azurerm_web_application_firewall_policy.this.name
}

# Unlike the AWS module there is no log group here. Azure emits WAF logs from
# the Application Gateway the policy is attached to, so the diagnostic setting
# belongs on that resource.
output "mode" {
  description = "Whether the policy blocks matches or only logs them"
  value       = var.mode
}
