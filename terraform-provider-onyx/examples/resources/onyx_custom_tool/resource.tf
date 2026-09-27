# A custom action lets an assistant call an external HTTP API. Onyx derives one
# callable method per operation, so every operation needs an operationId and
# either a summary or a description.
resource "onyx_custom_tool" "weather" {
  name        = "weather"
  description = "Looks up the current weather for a city"

  definition = jsonencode({
    openapi = "3.0.0"
    info = {
      title       = "Weather"
      description = "Current conditions by city"
    }
    servers = [{ url = "https://api.example.com" }]
    paths = {
      "/weather/{city}" = {
        get = {
          operationId = "getWeather"
          summary     = "Get the current weather for a city"
          parameters = [{
            name     = "city"
            in       = "path"
            required = true
            schema   = { type = "string" }
          }]
          responses = { "200" = { description = "Current conditions" } }
        }
      }
    }
  })

  # Sent with every call the action makes. These are secrets: keep them out of
  # the configuration itself and out of version control.
  custom_headers = {
    "X-Api-Key" = var.weather_api_key
  }
}

# Reading the definition from a file keeps a large schema out of the
# configuration.
resource "onyx_custom_tool" "billing" {
  name       = "billing"
  definition = file("${path.module}/openapi/billing.json")

  # Forward the calling user's Onyx credentials instead of a fixed key, so the
  # API applies that user's own permissions. It cannot be combined with an
  # Authorization header above.
  passthrough_auth = true
}

# An action can be turned off without being deleted, which leaves it configured
# but stops any assistant from calling it.
resource "onyx_custom_tool" "legacy_lookup" {
  name       = "legacy-lookup"
  definition = file("${path.module}/openapi/legacy.json")
  enabled    = false
}
