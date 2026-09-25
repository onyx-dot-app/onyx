# Cloud Armor backend security policy, the GCP counterpart of the AWS and Azure
# WAF modules.
#
# The policy only takes effect on an external Application Load Balancer (L7).
# Attach it with a GKE BackendConfig (spec.securityPolicy.name) for Ingress, or
# a GCPBackendPolicy (spec.default.securityPolicy) for Gateway. An L4 passthrough
# load balancer, such as ingress-nginx behind a Service of type LoadBalancer,
# cannot carry it: the policy then protects nothing and nothing reports that.
#
# Cloud Armor stops at the first rule that matches, lowest priority number
# first, so the bands below order the checks:
#   1000+  blocked ranges               deny(403)
#   2000   outside the allowlist        deny(403)
#   2100+  blocked countries            deny(403)
#   3000+  preconfigured WAF rules      deny(403)
#   4000+  rate limit exempt ranges     allow, so they skip both limits
#   5000   API path rate limit          throttle, deny(429)
#   5100   global rate limit            throttle, deny(429)
#   max    default                      allow

locals {
  policy_name = "${var.name}-waf"

  # A basic rule matches at most 10 ranges.
  blocked_chunks = chunklist(var.blocked_ip_cidrs, 10)
  exempt_chunks  = chunklist(var.rate_limit_exempt_ip_cidrs, 10)
  # An expression allows at most 10 subexpressions.
  country_chunks = chunklist(var.geo_restriction_countries, 10)

  waf_rule_keys = sort(keys(var.preconfigured_rules))

  waf_expressions = {
    for k, r in var.preconfigured_rules : k => format(
      "evaluatePreconfiguredWaf('%s-%s-stable', {'sensitivity': %d%s})",
      k,
      var.crs_version,
      coalesce(r.sensitivity, var.sensitivity),
      length(r.opt_out_rule_ids) > 0 ? format(", 'opt_out_rule_ids': [%s]", join(", ", [for id in r.opt_out_rule_ids : "'${id}'"])) : "",
    )
  }

  # Every rule carries the same attributes so the list has one element type.
  rules = concat(
    [for i, chunk in local.blocked_chunks : {
      priority      = 1000 + i
      action        = "deny(403)"
      description   = "Blocked address ranges"
      preview       = false
      src_ip_ranges = chunk
      expression    = null
      rate_limit    = null
    }],
    length(var.allowed_ip_cidrs) > 0 ? [{
      priority      = 2000
      action        = "deny(403)"
      description   = "Requests from outside the allowlist"
      preview       = false
      src_ip_ranges = null
      expression    = "!(${join(" || ", [for c in var.allowed_ip_cidrs : "inIpRange(origin.ip, '${c}')"])})"
      rate_limit    = null
    }] : [],
    [for i, chunk in local.country_chunks : {
      priority      = 2100 + i
      action        = "deny(403)"
      description   = "Blocked countries"
      preview       = false
      src_ip_ranges = null
      expression    = join(" || ", [for c in chunk : "origin.region_code == '${c}'"])
      rate_limit    = null
    }],
    [for i, k in local.waf_rule_keys : {
      priority      = 3000 + i
      action        = "deny(403)"
      description   = "OWASP CRS ${k}"
      preview       = coalesce(var.preconfigured_rules[k].preview, var.preview)
      src_ip_ranges = null
      expression    = local.waf_expressions[k]
      rate_limit    = null
    }],
    [for i, chunk in local.exempt_chunks : {
      priority      = 4000 + i
      action        = "allow"
      description   = "Rate limit exempt address ranges"
      preview       = false
      src_ip_ranges = chunk
      expression    = null
      rate_limit    = null
    }],
    # A throttle rule allows requests under its limit and stops there, so API
    # requests count against this limit only, not also against the global one.
    [{
      priority      = 5000
      action        = "throttle"
      description   = "API path rate limit per client address"
      preview       = var.preview
      src_ip_ranges = null
      expression    = "request.path.startsWith('${var.api_path_prefix}')"
      rate_limit    = { count = var.api_rate_limit_threshold }
    }],
    [{
      priority      = 5100
      action        = "throttle"
      description   = "Global rate limit per client address"
      preview       = var.preview
      src_ip_ranges = ["*"]
      expression    = null
      rate_limit    = { count = var.rate_limit_threshold }
    }],
    [{
      priority      = 2147483647
      action        = "allow"
      description   = "Default rule"
      preview       = false
      src_ip_ranges = ["*"]
      expression    = null
      rate_limit    = null
    }],
  )
}

resource "google_compute_security_policy" "this" {
  project     = var.project_id
  name        = local.policy_name
  description = coalesce(var.description, "WAF policy for ${var.name}")
  type        = "CLOUD_ARMOR"
  labels      = var.labels

  deletion_policy = var.deletion_protection ? "PREVENT" : "DELETE"

  advanced_options_config {
    # Without this the WAF rules read a JSON body as one opaque string.
    json_parsing                 = "STANDARD"
    log_level                    = var.log_level
    request_body_inspection_size = var.request_body_inspection_size
  }

  adaptive_protection_config {
    layer_7_ddos_defense_config {
      enable          = var.adaptive_protection_enabled
      rule_visibility = "STANDARD"
    }
  }

  dynamic "rule" {
    for_each = local.rules
    content {
      priority    = rule.value.priority
      action      = rule.value.action
      description = rule.value.description
      preview     = rule.value.preview

      match {
        versioned_expr = rule.value.src_ip_ranges != null ? "SRC_IPS_V1" : null

        dynamic "config" {
          for_each = rule.value.src_ip_ranges != null ? [rule.value.src_ip_ranges] : []
          content {
            src_ip_ranges = config.value
          }
        }

        dynamic "expr" {
          for_each = rule.value.expression != null ? [rule.value.expression] : []
          content {
            expression = expr.value
          }
        }
      }

      dynamic "rate_limit_options" {
        for_each = rule.value.rate_limit != null ? [rule.value.rate_limit] : []
        content {
          conform_action = "allow"
          exceed_action  = "deny(429)"
          enforce_on_key = "IP"

          rate_limit_threshold {
            count        = rate_limit_options.value.count
            interval_sec = var.rate_limit_interval_sec
          }
        }
      }
    }
  }

  lifecycle {
    # The whole evaluatePreconfiguredWaf call is one subexpression, which
    # Cloud Armor caps at 1024 characters. Long opt-out lists hit it.
    precondition {
      condition     = alltrue([for e in values(local.waf_expressions) : length(e) <= 1024])
      error_message = "A preconfigured rule expression is longer than the 1024 characters Cloud Armor allows. Shorten its opt_out_rule_ids or lower its sensitivity instead."
    }
  }
}
