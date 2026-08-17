data "onyx_settings" "current" {}

output "license_tier" {
  value = data.onyx_settings.current.tier
}
