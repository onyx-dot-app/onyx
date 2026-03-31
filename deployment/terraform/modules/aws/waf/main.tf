locals {
  name                  = var.name
  tags                  = var.tags
  ip_allowlist_enabled  = length(var.allowed_ip_cidrs) > 0
  managed_rule_priority = local.ip_allowlist_enabled ? 1 : 0
}

resource "aws_wafv2_ip_set" "allowed_ips" {
  count = local.ip_allowlist_enabled ? 1 : 0

  name               = "${local.name}-allowed-ips"
  description        = "IP allowlist for ${local.name}"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"
  addresses          = var.allowed_ip_cidrs

  tags = local.tags
}

# AWS WAFv2 Web ACL
resource "aws_wafv2_web_acl" "main" {
  name        = "${local.name}-web-acl"
  description = "WAF Web ACL for ${local.name}"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  dynamic "rule" {
    for_each = local.ip_allowlist_enabled ? [1] : []
    content {
      name     = "BlockRequestsOutsideAllowedIPs"
      priority = 1

      action {
        block {}
      }

      statement {
        not_statement {
          statement {
            ip_set_reference_statement {
              arn = aws_wafv2_ip_set.allowed_ips[0].arn
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "BlockRequestsOutsideAllowedIPsMetric"
        sampled_requests_enabled   = true
      }
    }
  }

  # AWS Managed Rules - Core Rule Set
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1 + local.managed_rule_priority

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        dynamic "rule_action_override" {
          for_each = var.common_rule_set_count_rules
          content {
            name = rule_action_override.value
            action_to_use {
              count {}
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesCommonRuleSetMetric"
      sampled_requests_enabled   = true
    }
  }

  # AWS Managed Rules - Known Bad Inputs
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2 + local.managed_rule_priority

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesKnownBadInputsRuleSetMetric"
      sampled_requests_enabled   = true
    }
  }

  # Rate Limiting Rule
  rule {
    name     = "RateLimitRule"
    priority = 3 + local.managed_rule_priority

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit_requests_per_5_minutes
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitRuleMetric"
      sampled_requests_enabled   = true
    }
  }

  # Geo Restriction (if enabled)
  dynamic "rule" {
    for_each = length(var.geo_restriction_countries) > 0 ? [1] : []
    content {
      name     = "GeoRestrictionRule"
      priority = 4 + local.managed_rule_priority

      action {
        block {}
      }

      statement {
        geo_match_statement {
          country_codes = var.geo_restriction_countries
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "GeoRestrictionRuleMetric"
        sampled_requests_enabled   = true
      }
    }
  }

  # IP Rate Limiting
  rule {
    name     = "APIRateLimitRule"
    priority = 5 + local.managed_rule_priority

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.api_rate_limit_requests_per_5_minutes
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "APIRateLimitRuleMetric"
      sampled_requests_enabled   = true
    }
  }

  # SQL Injection Protection
  rule {
    name     = "AWSManagedRulesSQLiRuleSet"
    priority = 6 + local.managed_rule_priority

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesSQLiRuleSetMetric"
      sampled_requests_enabled   = true
    }
  }

  # Anonymous IP Protection
  rule {
    name     = "AWSManagedRulesAnonymousIpList"
    priority = 7 + local.managed_rule_priority

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAnonymousIpList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesAnonymousIpListMetric"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}WebACLMetric"
    sampled_requests_enabled   = true
  }

  tags = local.tags
}

# WAF Logging Configuration (simplified - just CloudWatch)
resource "aws_cloudwatch_log_group" "waf_logs" {
  count             = var.enable_logging ? 1 : 0
  name              = "/aws/waf/${local.name}"
  retention_in_days = var.log_retention_days

  tags = local.tags
}
