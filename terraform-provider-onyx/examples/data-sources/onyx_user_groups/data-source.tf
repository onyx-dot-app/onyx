data "onyx_user_groups" "all" {}

locals {
  # Indexing the map fails the plan if the group is missing.
  group_ids      = { for g in data.onyx_user_groups.all.groups : g.name => g.id }
  basic_group_id = local.group_ids["Basic"]
}
