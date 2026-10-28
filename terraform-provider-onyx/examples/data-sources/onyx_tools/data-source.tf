data "onyx_tools" "all" {}

locals {
  search_tool_id = one([for t in data.onyx_tools.all.tools : t.id if t.in_code_tool_id == "SearchTool"])
}

resource "onyx_agent" "researcher" {
  name        = "Researcher"
  description = "Searches the indexed documents."
  tool_ids    = [local.search_tool_id]
}
