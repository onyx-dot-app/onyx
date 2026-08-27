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
