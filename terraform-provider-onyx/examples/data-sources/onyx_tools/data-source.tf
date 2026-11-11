data "onyx_tools" "all" {}

locals {
  # Indexing the map fails the plan if the action is missing.
  built_in_tool_ids = { for t in data.onyx_tools.all.tools : t.in_code_tool_id => t.id if t.in_code_tool_id != null }
  search_tool_id    = local.built_in_tool_ids["SearchTool"]
}

resource "onyx_agent" "researcher" {
  name        = "Researcher"
  description = "Searches the indexed documents."
  tool_ids    = [local.search_tool_id]
}
