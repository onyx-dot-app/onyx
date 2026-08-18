variable "ingest_group_id" {
  type        = number
  description = "Id of an existing Onyx user group; ids are assigned per deployment."
}

# A key for an internal integration. The key material is in
# onyx_api_key.ingest.api_key (sensitive, state-only).
resource "onyx_api_key" "ingest" {
  name      = "ingest-pipeline"
  group_ids = [var.ingest_group_id]
}
