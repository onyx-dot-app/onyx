# The deployment-wide default model. Referencing the provider's id also
# orders destroys correctly: the default is repointed/released before the
# provider holding it is deleted.
resource "onyx_llm_provider_default" "this" {
  provider_id = onyx_llm_provider.openai.id
  model_name  = "gpt-5"

  vision_provider_id = onyx_llm_provider.openai.id
  vision_model_name  = "gpt-5"
}
