terraform {
  required_providers {
    onyx = {
      source = "onyx-dot-app/onyx"
    }
  }
}

# Credentials can also come from ONYX_SERVER_URL / ONYX_API_KEY env vars.
provider "onyx" {
  endpoint = "https://onyx.internal.example.com"
  api_key  = var.onyx_api_key # an admin-role API key ("on_...")
}
