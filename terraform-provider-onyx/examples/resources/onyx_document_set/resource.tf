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

  # Private sets need Enterprise Edition. Group and user ids come from the
  # deployment, so read them from the admin panel or pass them in.
  is_public = false
  groups    = [4]
  users     = [var.hr_lead_user_id]
}

# Onyx rejects a set that holds nothing, so a set built only from federated
# connectors still needs at least one entry there.
#
# `entities` follows the schema of the connector it points at. Slack is the
# only federated source today, and takes the fields below.
resource "onyx_document_set" "support_channels" {
  name        = "support-channels"
  cc_pair_ids = []

  federated_connectors = [
    {
      federated_connector_id = var.slack_federated_connector_id
      entities = jsonencode({
        search_all_channels = false
        channels            = ["support", "support-escalations"]
      })
    },
  ]
}
