# A connector-credential pair is the object that actually indexes. It joins a
# connector to the credential it authenticates with, and carries the access
# control for the documents they produce.
resource "onyx_cc_pair" "confluence_wiki" {
  name          = "confluence-wiki"
  connector_id  = onyx_connector.confluence.id
  credential_id = onyx_credential.confluence.id

  # Everyone can read the indexed documents. Use "private" with groups to
  # restrict them, or "sync" to mirror permissions from the source system.
  access_type = "public"
}

# A pair whose documents only two groups may read.
resource "onyx_cc_pair" "hr_handbook" {
  name          = "hr-handbook"
  connector_id  = onyx_connector.hr_drive.id
  credential_id = onyx_credential.hr_drive.id

  # Group ids come from the Onyx admin panel. There is no user group
  # resource yet, so set them literally.
  access_type = "private"
  groups      = [4, 7]

  # Pause a pair to stop new index runs. It keeps the documents it has.
  paused = false
}

# Destroying a pair also removes the documents it indexed, which Onyx does in
# the background. Raise the timeout for a connector holding many documents.
resource "onyx_cc_pair" "large_archive" {
  name          = "large-archive"
  connector_id  = onyx_connector.archive.id
  credential_id = onyx_credential.archive.id

  timeouts {
    delete = "2h"
  }
}
