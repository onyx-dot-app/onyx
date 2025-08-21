variable "name" {
  type        = string
  description = "Name prefix for WAF resources"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to all WAF resources"
  default     = {}
}

variable "rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Rate limit for requests per 5 minutes per IP address"
  default     = 2000
}

variable "api_rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Rate limit for API requests per 5 minutes per IP address"
  default     = 1000
}

variable "geo_restriction_countries" {
  type        = list(string)
  description = "List of country codes to block. Leave empty to disable geo restrictions"
  default     = []
}

variable "enable_logging" {
  type        = bool
  description = "Enable WAF logging to S3"
  default     = true
}

variable "log_retention_days" {
  type        = number
  description = "Number of days to retain WAF logs"
  default     = 90
}
