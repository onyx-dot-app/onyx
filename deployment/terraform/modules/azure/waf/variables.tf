variable "name" {
  type        = string
  description = "Name prefix for the policy"
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the policy"
}

variable "location" {
  type        = string
  description = "Azure region, for example \"eastus\". The policy is regional, like the AWS module's REGIONAL web ACL."
}

# Detection is the whole-policy equivalent of overriding every AWS managed rule
# to COUNT: rules still evaluate and log, but nothing is blocked.
variable "mode" {
  type        = string
  description = "Prevention blocks what the rules match. Detection only logs it, which is the way to see what a new policy would do before it does it."
  default     = "Prevention"

  validation {
    condition     = contains(["Prevention", "Detection"], var.mode)
    error_message = "mode must be Prevention or Detection."
  }
}

variable "owasp_rule_set_version" {
  type        = string
  description = "OWASP Core Rule Set version. This one set covers what the AWS module gets from the common, known-bad-inputs and SQL injection rule groups."
  default     = "3.2"

  validation {
    condition     = contains(["3.0", "3.1", "3.2"], var.owasp_rule_set_version)
    error_message = "owasp_rule_set_version must be one of: 3.0, 3.1, 3.2."
  }
}

variable "enable_bot_protection" {
  type        = bool
  description = "Add the Microsoft bot manager rule set, the counterpart of the AWS anonymous IP list"
  default     = true
}

variable "bot_manager_rule_set_version" {
  type        = string
  description = "Microsoft bot manager rule set version"
  default     = "1.0"
}

# Azure identifies a rule by group and numeric id rather than by name, so this
# replaces the AWS module's list of subrule names to override to COUNT.
variable "managed_rule_overrides" {
  type = list(object({
    rule_group_name = string
    rule_id         = string
    action          = optional(string, "Log")
    enabled         = optional(bool, true)
    rule_set_type   = optional(string, "OWASP")
  }))
  description = <<-EOT
    Individual managed rules to re-aim or switch off, for example a rule that
    fires on a legitimate request shape. Azure identifies a rule by its group
    and numeric id rather than by name.

    The OWASP set carries these groups:
      General, REQUEST-911-METHOD-ENFORCEMENT, REQUEST-913-SCANNER-DETECTION,
      REQUEST-920-PROTOCOL-ENFORCEMENT, REQUEST-921-PROTOCOL-ATTACK,
      REQUEST-930-APPLICATION-ATTACK-LFI, REQUEST-931-APPLICATION-ATTACK-RFI,
      REQUEST-932-APPLICATION-ATTACK-RCE, REQUEST-933-APPLICATION-ATTACK-PHP,
      REQUEST-941-APPLICATION-ATTACK-XSS, REQUEST-942-APPLICATION-ATTACK-SQLI,
      REQUEST-943-APPLICATION-ATTACK-SESSION-FIXATION,
      REQUEST-944-APPLICATION-ATTACK-JAVA

    The bot manager set carries BadBots, GoodBots and UnknownBots.
  EOT
  default     = []

  validation {
    condition     = alltrue([for o in var.managed_rule_overrides : contains(["Allow", "Block", "Log", "JSChallenge", "AnomalyScoring"], o.action)])
    error_message = "Each override action must be one of: Allow, Block, Log, JSChallenge, AnomalyScoring."
  }

  # An override that names a rule set the policy does not carry is dropped on
  # the way through, leaving the rule doing exactly what the caller meant to
  # change. Both cases are caught here instead.
  validation {
    condition     = alltrue([for o in var.managed_rule_overrides : contains(["OWASP", "Microsoft_BotManagerRuleSet"], o.rule_set_type)])
    error_message = "Each override rule_set_type must be OWASP or Microsoft_BotManagerRuleSet."
  }

  validation {
    condition     = var.enable_bot_protection || alltrue([for o in var.managed_rule_overrides : o.rule_set_type != "Microsoft_BotManagerRuleSet"])
    error_message = "An override targets Microsoft_BotManagerRuleSet, but enable_bot_protection is false, so that rule set is not on the policy and the override would do nothing."
  }

  # A group name from the wrong rule set, or a misspelled one, produces a group
  # override Azure accepts and never applies.
  validation {
    condition = alltrue([
      for o in var.managed_rule_overrides : contains(
        o.rule_set_type == "OWASP" ? [
          "General",
          "REQUEST-911-METHOD-ENFORCEMENT",
          "REQUEST-913-SCANNER-DETECTION",
          "REQUEST-920-PROTOCOL-ENFORCEMENT",
          "REQUEST-921-PROTOCOL-ATTACK",
          "REQUEST-930-APPLICATION-ATTACK-LFI",
          "REQUEST-931-APPLICATION-ATTACK-RFI",
          "REQUEST-932-APPLICATION-ATTACK-RCE",
          "REQUEST-933-APPLICATION-ATTACK-PHP",
          "REQUEST-941-APPLICATION-ATTACK-XSS",
          "REQUEST-942-APPLICATION-ATTACK-SQLI",
          "REQUEST-943-APPLICATION-ATTACK-SESSION-FIXATION",
          "REQUEST-944-APPLICATION-ATTACK-JAVA",
        ] : ["BadBots", "GoodBots", "UnknownBots"],
        o.rule_group_name,
      )
    ])
    error_message = "An override names a rule group its rule set does not carry. See the variable description for the groups each set has."
  }
}

variable "allowed_ip_cidrs" {
  type        = list(string)
  description = "IPv4 or IPv6 ranges allowed to reach the application. Empty disables the allowlist and lets every address through to the rest of the rules."
  default     = []
}

variable "rate_limit_exempt_ip_cidrs" {
  type        = list(string)
  description = "Ranges exempt from both rate limits. Typically an office or VPN range whose users share one address."
  default     = []
}

variable "rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Requests per 5 minutes from one address before blocking"
  default     = 2000

  validation {
    condition     = var.rate_limit_requests_per_5_minutes > 0
    error_message = "rate_limit_requests_per_5_minutes must be greater than 0."
  }
}

variable "api_rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Requests per 5 minutes from one address to the API path before blocking"
  default     = 1000

  validation {
    condition     = var.api_rate_limit_requests_per_5_minutes > 0
    error_message = "api_rate_limit_requests_per_5_minutes must be greater than 0."
  }
}

variable "api_path_prefix" {
  type        = string
  description = "Path prefix the stricter rate limit applies to"
  default     = "/api"
}

variable "geo_restriction_countries" {
  type        = list(string)
  description = "Two-letter country codes to block. Empty disables geo blocking."
  default     = []

  validation {
    condition     = alltrue([for c in var.geo_restriction_countries : can(regex("^[A-Z]{2}$", c))])
    error_message = "Country codes must be two uppercase letters, for example \"CN\"."
  }
}

variable "max_request_body_size_in_kb" {
  type        = number
  description = "Largest request body the WAF will inspect"
  default     = 128

  validation {
    condition     = var.max_request_body_size_in_kb >= 8 && var.max_request_body_size_in_kb <= 2000
    error_message = "max_request_body_size_in_kb must be between 8 and 2000 (Azure limit)."
  }
}

variable "file_upload_limit_in_mb" {
  type        = number
  description = "Largest file upload allowed through. Onyx accepts document uploads, so this needs to clear the largest file a user will send."
  default     = 750

  validation {
    condition     = var.file_upload_limit_in_mb >= 1 && var.file_upload_limit_in_mb <= 4000
    error_message = "file_upload_limit_in_mb must be between 1 and 4000 (Azure limit)."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to the policy"
  default     = {}
}
