# An agent (assistant) pairs instructions with the knowledge and actions it may
# use. Agent names are unique across the deployment.
resource "onyx_persona" "support" {
  name        = "Support"
  description = "Answers customer questions from the handbook"

  system_prompt = <<-EOT
    You are a support agent. Answer from the handbook only.
    If the handbook does not cover the question, say so and offer to escalate.
  EOT

  # Appended to each user message.
  task_prompt = "Cite the handbook section you used."

  document_set_ids = [onyx_document_set.handbook.id]
  tool_ids         = [onyx_custom_tool.weather.id]

  starter_messages = [
    {
      name    = "Refunds"
      message = "How do refunds work?"
    },
    {
      name    = "Shipping"
      message = "How long does shipping take?"
    },
  ]
}

# An agent that only its group may use, kept out of the assistant list.
resource "onyx_persona" "hr_private" {
  name          = "HR"
  description   = "Answers policy questions for the HR team"
  system_prompt = "You answer HR policy questions."

  document_set_ids = [onyx_document_set.hr_private.id]

  # A hidden agent still works for anyone holding a link to it.
  is_listed = false

  # Private agents need Enterprise Edition. Group and user ids come from the
  # deployment, so read them from the admin panel or pass them in.
  is_public = false
  groups    = [4]
  users     = [var.hr_lead_user_id]
}

# Onyx promotes a featured agent to users. Ignoring documents from before a
# migration keeps an agent off stale material.
resource "onyx_persona" "onboarding" {
  name          = "Onboarding"
  description   = "Walks new starters through their first week"
  system_prompt = "You help new employees get set up."

  document_set_ids  = [onyx_document_set.handbook.id]
  is_featured       = true
  display_priority  = 1
  icon_name         = "user"
  search_start_date = "2026-01-01"
}
