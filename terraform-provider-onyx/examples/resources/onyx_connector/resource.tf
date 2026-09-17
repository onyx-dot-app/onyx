# A connector says what to index and how often.
resource "onyx_connector" "docs_site" {
  name       = "docs-site"
  source     = "web"
  input_type = "load_state"

  # Re-index once a day, prune monthly.
  refresh_freq = 24 * 60 * 60
  prune_freq   = 30 * 24 * 60 * 60

  connector_specific_config = jsonencode({
    base_url           = "https://example.com/docs"
    web_connector_type = "recursive"
  })
}
