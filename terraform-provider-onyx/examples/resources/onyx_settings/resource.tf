# Only the attributes set here are managed; everything else is left
# untouched server-side. Destroying this resource does NOT reset settings.
resource "onyx_settings" "workspace" {
  company_name        = "ACME Corp"
  invite_only_enabled = true
  query_history_type  = "anonymized"
}
