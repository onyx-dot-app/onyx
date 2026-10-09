# A group with nothing but a name. Members can be added later, from here or
# from the admin panel — but note the configuration wins on the next apply.
resource "onyx_user_group" "everyone_uk" {
  name = "UK"
}

# A team that administers connectors and document sets, with two of its members
# managing the roster.
#
# Permissions use Onyx's own tokens, not the enum names. Only toggleable ones
# can be set: `basic`, `admin`, `craft_sandbox` and `manage:skills` are managed
# by Onyx and are refused here.
resource "onyx_user_group" "data_platform" {
  name = "Data Platform"

  user_ids = [
    "3f6c1e2a-0b4d-4c8e-9a1f-2d5b7c9e0a13",
    "8d2b5f71-6c3a-4e19-b0d7-1a4f8c2e5b60",
    "c1a94e08-7f2d-4b63-8e15-9d0c3a6f4b27",
  ]

  # Every manager must also appear in user_ids: Onyx stores the flag on the
  # membership row, so a manager is always a member.
  manager_ids = [
    "3f6c1e2a-0b4d-4c8e-9a1f-2d5b7c9e0a13",
    "8d2b5f71-6c3a-4e19-b0d7-1a4f8c2e5b60",
  ]

  permissions = [
    "manage:connectors",
    "manage:document_sets",
    "read:query_history",
  ]
}

# What a group can see is set from the other side. The connector owns this
# link, so the group never fights it for the same edge.
resource "onyx_cc_pair" "sales_drive" {
  name          = "Sales Drive"
  connector_id  = onyx_connector.drive.id
  credential_id = onyx_credential.drive.id
  access_type   = "private"
  groups        = [onyx_user_group.data_platform.id]
}
