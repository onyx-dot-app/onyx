# A key for an internal integration. The key material is in
# onyx_api_key.ingest.api_key (sensitive, state-only).
resource "onyx_api_key" "ingest" {
  name = "ingest-pipeline"
  role = "basic"
}
