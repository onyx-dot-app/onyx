variable "name" {
  type        = string
  description = "Name prefix for the policy. The policy is named \"<name>-waf\"."

  # "-waf" takes four of the 63 characters a Compute Engine name allows.
  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,57}[a-z0-9])?$", var.name))
    error_message = "name must be 1-59 characters of lowercase letters, digits and hyphens, start with a letter and not end with a hyphen."
  }
}

variable "project_id" {
  type        = string
  description = "Project that holds the policy"

  validation {
    condition     = can(regex("^([a-z][a-z0-9.-]*[a-z0-9]:)?[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project ID."
  }
}

variable "description" {
  type        = string
  description = "Policy description. Null uses \"WAF policy for <name>\"."
  default     = null
}

# The AWS module runs managed rule groups that come in one fixed version; here
# the OWASP Core Rule Set version is a choice, and the rule names carry it.
variable "crs_version" {
  type        = string
  description = "OWASP Core Rule Set version the preconfigured rules come from: v33 (CRS 3.3) or v422 (CRS 4.22)."
  default     = "v33"

  validation {
    condition     = contains(["v33", "v422"], var.crs_version)
    error_message = "crs_version must be v33 or v422."
  }
}

variable "preconfigured_rules" {
  type = map(object({
    sensitivity      = optional(number)
    preview          = optional(bool)
    opt_out_rule_ids = optional(list(string), [])
  }))
  description = <<-EOT
    Preconfigured WAF rule sets to enforce, keyed by rule set short name. Each
    becomes one rule evaluating "<key>-<crs_version>-stable". The defaults cover
    what the AWS module gets from its common, known-bad-inputs and SQLi groups.

    sensitivity and preview fall back to the module-wide values when unset.
    opt_out_rule_ids switches off single signatures that fire on a legitimate
    request shape, the counterpart of the AWS common_rule_set_count_rules, for
    example "owasp-crs-v030301-id942421-sqli".

    v33 carries: sqli, xss, lfi, rfi, rce, scannerdetection, protocolattack,
    sessionfixation, methodenforcement, php, java, nodejs.
    v422 carries the same without nodejs, plus generic.
  EOT
  default = {
    sqli             = {}
    xss              = {}
    lfi              = {}
    rfi              = {}
    rce              = {}
    scannerdetection = {}
    protocolattack   = {}
    sessionfixation  = {}
  }

  # A rule set that does not exist in the chosen CRS version would be rejected
  # at apply time at best, so it is caught here with the reason.
  validation {
    condition = alltrue([
      for k in keys(var.preconfigured_rules) : contains(
        var.crs_version == "v33" ? [
          "sqli", "xss", "lfi", "rfi", "rce", "scannerdetection", "protocolattack",
          "sessionfixation", "methodenforcement", "php", "java", "nodejs",
          ] : [
          "sqli", "xss", "lfi", "rfi", "rce", "scannerdetection", "protocolattack",
          "sessionfixation", "methodenforcement", "php", "java", "generic",
        ],
        k,
      )
    ])
    error_message = "A preconfigured_rules key names a rule set the chosen crs_version does not carry. See the variable description for the sets each version has."
  }

  validation {
    condition = alltrue([
      for r in values(var.preconfigured_rules) : r.sensitivity == null || contains([1, 2, 3, 4], r.sensitivity)
    ])
    error_message = "Each rule sensitivity must be 1, 2, 3 or 4."
  }

  # A signature ID from another rule set or CRS version matches nothing, so the
  # opt-out would do nothing and the signature would keep firing.
  validation {
    condition = alltrue(flatten([
      for k, r in var.preconfigured_rules : [
        for id in r.opt_out_rule_ids :
        can(regex("^owasp-crs-${var.crs_version == "v33" ? "v030301" : "v042200"}-id[0-9]{6}-${k}$", id))
      ]
    ]))
    error_message = "Each opt_out_rule_ids entry must be a signature from its own rule set and the chosen crs_version, for example owasp-crs-v030301-id942421-sqli for sqli on v33 or owasp-crs-v042200-id942421-sqli on v422."
  }
}

# Sensitivity is the Cloud Armor name for the CRS paranoia level. Cloud Armor
# runs every signature (level 4) when none is given, which false-positives on
# ordinary traffic; 1 is the CRS default and what the Azure module runs.
variable "sensitivity" {
  type        = number
  description = "Default sensitivity for every preconfigured rule set, 1 (fewest false positives) to 4 (every signature)"
  default     = 1

  validation {
    condition     = contains([1, 2, 3, 4], var.sensitivity)
    error_message = "sensitivity must be 1, 2, 3 or 4."
  }
}

# The whole-policy equivalent of Azure Detection mode. IP and country rules
# still enforce, because the caller listed those addresses on purpose.
variable "preview" {
  type        = bool
  description = "Log what the WAF and rate limit rules match instead of acting on it. A per-rule preview in preconfigured_rules overrides this."
  default     = false
}

variable "rate_limit_threshold" {
  type        = number
  description = "Requests per interval from one address before it gets 429s"
  default     = 2000

  validation {
    condition     = var.rate_limit_threshold >= 1 && var.rate_limit_threshold <= 1000000 && floor(var.rate_limit_threshold) == var.rate_limit_threshold
    error_message = "rate_limit_threshold must be a whole number from 1 to 1000000 (Cloud Armor limit)."
  }
}

variable "rate_limit_interval_sec" {
  type        = number
  description = "Window the rate limits count over. The default matches the five minutes the AWS and Azure modules use."
  default     = 300

  validation {
    condition     = contains([10, 30, 60, 120, 180, 240, 300, 600, 900, 1200, 1800, 2700, 3600], var.rate_limit_interval_sec)
    error_message = "rate_limit_interval_sec must be one of 10, 30, 60, 120, 180, 240, 300, 600, 900, 1200, 1800, 2700 or 3600."
  }
}

variable "api_rate_limit_threshold" {
  type        = number
  description = "Requests per interval from one address to api_path_prefix before it gets 429s"
  default     = 1000

  validation {
    condition     = var.api_rate_limit_threshold >= 1 && var.api_rate_limit_threshold <= 1000000 && floor(var.api_rate_limit_threshold) == var.api_rate_limit_threshold
    error_message = "api_rate_limit_threshold must be a whole number from 1 to 1000000 (Cloud Armor limit)."
  }
}

variable "api_path_prefix" {
  type        = string
  description = "Path prefix the stricter rate limit applies to"
  default     = "/api"

  # The prefix is written into a rule expression inside single quotes.
  validation {
    condition     = can(regex("^/[A-Za-z0-9/_.~-]*$", var.api_path_prefix))
    error_message = "api_path_prefix must start with / and contain only letters, digits and / _ . ~ -."
  }
}

variable "allowed_ip_cidrs" {
  type        = list(string)
  description = "IPv4 or IPv6 ranges allowed to reach the application. Empty disables the allowlist and lets every address through to the rest of the rules."
  default     = []

  validation {
    condition     = alltrue([for c in var.allowed_ip_cidrs : can(cidrhost(c, 0))])
    error_message = "Each allowed_ip_cidrs entry must be a CIDR range, for example 203.0.113.0/24."
  }

  # The allowlist is one negated expression, and Cloud Armor allows 10
  # subexpressions per expression. Splitting it over rules would not work:
  # an address outside one chunk is not outside the list.
  validation {
    condition     = length(var.allowed_ip_cidrs) <= 10
    error_message = "allowed_ip_cidrs holds at most 10 ranges, the Cloud Armor subexpression limit for one rule. Summarize the ranges into wider ones."
  }
}

variable "blocked_ip_cidrs" {
  type        = list(string)
  description = "IPv4 or IPv6 ranges refused with 403 before any other rule, including addresses on the allowlist"
  default     = []

  validation {
    condition     = alltrue([for c in var.blocked_ip_cidrs : can(cidrhost(c, 0))])
    error_message = "Each blocked_ip_cidrs entry must be a CIDR range, for example 203.0.113.0/24."
  }
}

variable "rate_limit_exempt_ip_cidrs" {
  type        = list(string)
  description = "Ranges exempt from both rate limits, typically an office or VPN range whose users share one address. The WAF rules still apply to them."
  default     = []

  validation {
    condition     = alltrue([for c in var.rate_limit_exempt_ip_cidrs : can(cidrhost(c, 0))])
    error_message = "Each rate_limit_exempt_ip_cidrs entry must be a CIDR range, for example 203.0.113.0/24."
  }
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

# Standard-tier projects get basic alerts only; the attack signature and a
# suggested rule need Cloud Armor Enterprise.
variable "adaptive_protection_enabled" {
  type        = bool
  description = "Enable Adaptive Protection layer 7 DDoS detection"
  default     = true
}

variable "log_level" {
  type        = string
  description = "NORMAL logs the matched rule. VERBOSE also logs the request fields that matched, for tuning false positives."
  default     = "NORMAL"

  validation {
    condition     = contains(["NORMAL", "VERBOSE"], var.log_level)
    error_message = "log_level must be NORMAL or VERBOSE."
  }
}

# Anything past this point in the body goes uninspected, so a small limit lets
# an attacker pad the payload past it. 64KB is the Cloud Armor maximum.
variable "request_body_inspection_size" {
  type        = string
  description = "How much of each request body the preconfigured rules inspect"
  default     = "64KB"

  validation {
    condition     = contains(["8KB", "16KB", "32KB", "48KB", "64KB"], var.request_body_inspection_size)
    error_message = "request_body_inspection_size must be one of 8KB, 16KB, 32KB, 48KB or 64KB."
  }
}

variable "deletion_protection" {
  type        = bool
  description = "Make Terraform refuse to delete or replace the policy"
  default     = true
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to the policy"
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.labels : can(regex("^[a-z][a-z0-9_-]{0,62}$", k)) && can(regex("^[a-z0-9_-]{0,63}$", v))
    ])
    error_message = "Label keys must start with a lowercase letter and contain only lowercase letters, digits, _ and -, up to 63 characters. Values follow the same rules and may be empty."
  }
}
