resource "onyx_llm_provider" "openai" {
  name          = "openai-prod"
  provider_type = "openai"
  # api_key is kept in Terraform state. To keep the key out of state, swap in
  # the write-only pair instead (needs Terraform 1.11 or later):
  #   api_key_wo         = var.openai_api_key
  #   api_key_wo_version = 1
  api_key = var.openai_api_key

  # The complete set of enabled models: anything omitted here is
  # removed from the provider on apply.
  model_configurations = [
    { name = "gpt-5" },
    {
      name                = "gpt-5-mini"
      custom_display_name = "GPT-5 Mini (cheap tier)"
    },
    {
      name       = "gpt-5-nano"
      is_visible = false
    },
  ]
}
