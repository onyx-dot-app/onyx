resource "onyx_agent_label" "engineering" {
  name = "Engineering"
}

resource "onyx_agent" "oncall" {
  name        = "On-call helper"
  description = "Answers questions about runbooks."
  label_ids   = [onyx_agent_label.engineering.id]
}
