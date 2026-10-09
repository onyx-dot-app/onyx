# Keep api_key set in configuration: the Onyx API replaces all fields on
# update, so applying without it clears the stored key.
resource "onyx_embedding_provider" "cohere" {
  provider_type = "cohere"
  api_key       = var.cohere_api_key
}
