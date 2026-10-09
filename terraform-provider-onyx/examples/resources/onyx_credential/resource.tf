# Credentials hold the secret a connector authenticates with. Keep the values
# in variables or a secret store — never in version control.
resource "onyx_credential" "confluence" {
  source = "confluence"
  name   = "confluence-service-account"

  credential_json = jsonencode({
    confluence_username     = var.confluence_username
    confluence_access_token = var.confluence_access_token
  })
}

# The same credential with a write-only payload. Terraform sends it on every
# apply and stores none of it, so the secret never reaches a state file.
# Needs Terraform 1.11 or later.
resource "onyx_credential" "confluence_write_only" {
  source = "confluence"
  name   = "confluence-service-account-wo"

  credential_json_wo = jsonencode({
    confluence_username     = var.confluence_username
    confluence_access_token = var.confluence_access_token
  })

  # Terraform cannot diff a value it never stores. Raise this counter to make
  # the next apply send a rotated payload.
  credential_json_wo_version = 1
}
