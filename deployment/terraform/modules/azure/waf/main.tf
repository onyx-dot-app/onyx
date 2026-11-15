locals {
  ip_allowlist_enabled      = length(var.allowed_ip_cidrs) > 0
  rate_limit_exempt_enabled = length(var.rate_limit_exempt_ip_cidrs) > 0
  geo_restriction_enabled   = length(var.geo_restriction_countries) > 0

  managed_rule_sets = concat(
    [{ type = "OWASP", version = var.owasp_rule_set_version }],
    var.enable_bot_protection ? [{ type = "Microsoft_BotManagerRuleSet", version = var.bot_manager_rule_set_version }] : [],
  )

  # The overrides arrive as a flat list but the provider nests them by rule set
  # and then by rule group, so regroup them once here.
  overrides_by_set = {
    for set_type in distinct([for o in var.managed_rule_overrides : o.rule_set_type]) :
    set_type => {
      for group_name in distinct([for o in var.managed_rule_overrides : o.rule_group_name if o.rule_set_type == set_type]) :
      group_name => [for o in var.managed_rule_overrides : o if o.rule_set_type == set_type && o.rule_group_name == group_name]
    }
  }
}

resource "azurerm_web_application_firewall_policy" "this" {
  name                = "${var.name}-waf"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags

  policy_settings {
    enabled                     = true
    mode                        = var.mode
    request_body_check          = true
    max_request_body_size_in_kb = var.max_request_body_size_in_kb
    file_upload_limit_in_mb     = var.file_upload_limit_in_mb
  }

  managed_rules {
    dynamic "managed_rule_set" {
      for_each = local.managed_rule_sets
      content {
        type    = managed_rule_set.value.type
        version = managed_rule_set.value.version

        dynamic "rule_group_override" {
          for_each = try(local.overrides_by_set[managed_rule_set.value.type], {})
          content {
            rule_group_name = rule_group_override.key

            dynamic "rule" {
              for_each = rule_group_override.value
              content {
                id      = rule.value.rule_id
                action  = rule.value.action
                enabled = rule.value.enabled
              }
            }
          }
        }
      }
    }
  }

  # Anything not on the allowlist is refused before the managed rules run.
  dynamic "custom_rules" {
    for_each = local.ip_allowlist_enabled ? [1] : []
    content {
      name      = "BlockRequestsOutsideAllowedIPs"
      priority  = 1
      rule_type = "MatchRule"
      action    = "Block"

      match_conditions {
        match_variables {
          variable_name = "RemoteAddr"
        }
        operator           = "IPMatch"
        negation_condition = true
        match_values       = var.allowed_ip_cidrs
      }
    }
  }

  dynamic "custom_rules" {
    for_each = local.geo_restriction_enabled ? [1] : []
    content {
      name      = "BlockRestrictedCountries"
      priority  = 10
      rule_type = "MatchRule"
      action    = "Block"

      match_conditions {
        match_variables {
          variable_name = "RemoteAddr"
        }
        operator     = "GeoMatch"
        match_values = var.geo_restriction_countries
      }
    }
  }

  # Match conditions on a rule are combined with AND, so the negated exempt
  # list is what keeps the limit from applying to those addresses.
  custom_rules {
    name                 = "ApiRateLimit"
    priority             = 20
    rule_type            = "RateLimitRule"
    action               = "Block"
    rate_limit_duration  = "FiveMins"
    rate_limit_threshold = var.api_rate_limit_requests_per_5_minutes
    group_rate_limit_by  = "ClientAddr"

    match_conditions {
      match_variables {
        variable_name = "RequestUri"
      }
      operator     = "BeginsWith"
      match_values = [var.api_path_prefix]
    }

    dynamic "match_conditions" {
      for_each = local.rate_limit_exempt_enabled ? [1] : []
      content {
        match_variables {
          variable_name = "RemoteAddr"
        }
        operator           = "IPMatch"
        negation_condition = true
        match_values       = var.rate_limit_exempt_ip_cidrs
      }
    }
  }

  custom_rules {
    name                 = "GlobalRateLimit"
    priority             = 30
    rule_type            = "RateLimitRule"
    action               = "Block"
    rate_limit_duration  = "FiveMins"
    rate_limit_threshold = var.rate_limit_requests_per_5_minutes
    group_rate_limit_by  = "ClientAddr"

    match_conditions {
      match_variables {
        variable_name = "RemoteAddr"
      }
      operator     = "IPMatch"
      match_values = ["0.0.0.0/0", "::/0"]
    }

    dynamic "match_conditions" {
      for_each = local.rate_limit_exempt_enabled ? [1] : []
      content {
        match_variables {
          variable_name = "RemoteAddr"
        }
        operator           = "IPMatch"
        negation_condition = true
        match_values       = var.rate_limit_exempt_ip_cidrs
      }
    }
  }
}
