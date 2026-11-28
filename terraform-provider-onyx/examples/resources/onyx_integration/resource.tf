variable "weather_api_key" {
  type      = string
  sensitive = true
}

# An MCP server with one API key for the organization.
resource "onyx_integration" "weather" {
  name                                = "Weather"
  description                         = "Forecasts and alerts."
  server_url                          = "https://mcp.example.com/mcp"
  auth_mode                           = "shared"
  auth_method                         = "api_key"
  header_template                     = { Authorization = "Bearer {api_key}" }
  organization_credentials_wo         = { api_key = var.weather_api_key }
  organization_credentials_wo_version = 1
}

# An HTTP API from an OpenAPI document. Each user signs in with their own key.
resource "onyx_integration" "tickets" {
  name             = "Tickets"
  openapi_document = file("${path.module}/tickets.openapi.yaml")
  auth_mode        = "individual"
  auth_method      = "api_key"
  header_template  = { "X-Api-Key" = "{api_key}" }
}
