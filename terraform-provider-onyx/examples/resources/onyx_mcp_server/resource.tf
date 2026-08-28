# A public MCP server that needs no credentials.
resource "onyx_mcp_server" "docs" {
  name        = "Docs"
  description = "Public documentation search"
  server_url  = "https://mcp.example.com/mcp"
}

# A server behind one shared API token. Onyx returns the token masked, so the
# configuration is the only record of it: rotate it here, never in the UI.
resource "onyx_mcp_server" "weather" {
  name           = "Weather"
  server_url     = "https://weather.example.com/mcp"
  auth_type      = "API_TOKEN"
  auth_performer = "ADMIN"
  api_token      = var.weather_api_token

  # Only the Craft agent may reach this one.
  available_in_craft = true
  is_public          = false
}

# A server where every user supplies their own key. The template names the
# fields they fill in; admin_credentials are the applying admin's own values.
resource "onyx_mcp_server" "tickets" {
  name           = "Tickets"
  server_url     = "https://tickets.example.com/mcp"
  auth_type      = "API_TOKEN"
  auth_performer = "PER_USER"

  auth_template_headers = {
    "X-Api-Key" = "{api_key}"
  }
  admin_credentials = {
    api_key = var.tickets_admin_api_key
  }
}
