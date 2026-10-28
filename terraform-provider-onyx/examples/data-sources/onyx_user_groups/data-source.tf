data "onyx_user_groups" "all" {}

locals {
  basic_group_id = one([for g in data.onyx_user_groups.all.groups : g.id if g.name == "Basic"])
}
