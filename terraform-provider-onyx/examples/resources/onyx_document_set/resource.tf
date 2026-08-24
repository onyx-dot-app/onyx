# A document set groups connector-credential pairs so users and assistants can
# search them as one unit.
resource "onyx_document_set" "engineering" {
  name        = "engineering"
  description = "Design docs, runbooks and the internal wiki"

  cc_pair_ids = [
    onyx_cc_pair.confluence_wiki.id,
    onyx_cc_pair.github_docs.id,
  ]
}

# A set only two groups may use.
resource "onyx_document_set" "hr_private" {
  name        = "hr-private"
  description = "Handbook and policies"

  cc_pair_ids = [onyx_cc_pair.hr_handbook.id]

  is_public = false
  groups    = [4]
  users     = ["4f1c8f3e-1a2b-4c5d-8e9f-0a1b2c3d4e5f"]
}

# Onyx rejects a set that holds nothing, so a set built only from federated
# connectors still needs at least one entry there.
resource "onyx_document_set" "support_tickets" {
  name        = "support-tickets"
  cc_pair_ids = []

  federated_connectors = [
    {
      federated_connector_id = "2"
      entities               = jsonencode({ ticket_status = "open" })
    },
  ]
}
