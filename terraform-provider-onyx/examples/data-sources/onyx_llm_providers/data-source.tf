data "onyx_llm_providers" "all" {}

output "default_model" {
  value = data.onyx_llm_providers.all.default_text
}
