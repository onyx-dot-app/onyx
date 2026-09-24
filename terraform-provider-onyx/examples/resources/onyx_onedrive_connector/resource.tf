resource "onyx_credential" "onedrive" {
  source = "onedrive"
  name   = "onedrive-certificate"

  credential_json_wo = jsonencode({
    authentication_method         = "certificate"
    onedrive_client_id            = var.onedrive_client_id
    onedrive_directory_id         = var.onedrive_directory_id
    onedrive_private_key          = var.onedrive_private_key
    onedrive_certificate_password = var.onedrive_certificate_password
  })

  credential_json_wo_version = 1
}

resource "onyx_connector" "onedrive" {
  name       = "onedrive"
  source     = "onedrive"
  input_type = "poll"

  connector_specific_config = jsonencode({
    users = var.onedrive_users
  })
}

resource "onyx_cc_pair" "onedrive" {
  name          = "onedrive"
  connector_id  = onyx_connector.onedrive.id
  credential_id = onyx_credential.onedrive.id
  access_type   = "sync"
}
