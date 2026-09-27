variable "onyx_server_url" {
  type        = string
  description = "Base URL of the Onyx deployment, for example https://onyx.example.com. Falls back to ONYX_SERVER_URL."
  default     = null
}

variable "onyx_api_key" {
  type        = string
  description = "An Onyx API key in the Admin group. Falls back to ONYX_API_KEY. Run ./mint_api_key.sh to create one."
  sensitive   = true
  default     = null
}

variable "openai_api_key" {
  type        = string
  description = "OpenAI API key for the chat model."
  sensitive   = true
}

variable "company_name" {
  type        = string
  description = "Workspace name shown in the Onyx UI."
  default     = "ACME Corp"
}

variable "docs_base_url" {
  type        = string
  description = "Public documentation site to index."
  default     = "https://docs.onyx.app"
}

variable "enable_enterprise_features" {
  type        = bool
  description = "Set true only on a deployment with Enterprise Edition enabled. Community Edition rejects the user group routes."
  default     = false
}
