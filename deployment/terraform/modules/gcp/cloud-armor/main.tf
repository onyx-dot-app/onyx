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
#   3000+  preconfigured WAF rules      deny(403), tuned for Onyx traffic
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

  # Rule sets left untuned, because nothing Onyx sends trips them. The rest
  # read field values, and an Onyx field value is often code, a URL or a secret.
  untuned_rule_sets = ["methodenforcement", "scannerdetection", "sessionfixation"]

  # The standard WAF tuning: a signature keeps running but does not read the
  # value of a named field. These are the Onyx fields that hold chat text,
  # prompts, code, URLs and secrets, which the signatures match at any
  # sensitivity. A field missing here shows up as a 403 and a load balancer
  # log line naming the signature.
  default_uninspected_fields = [
    # chat and prompts
    "message", "query", "user_query", "prompt", "system_prompt", "task_prompt",
    "instructions", "instructions_markdown", "description", "content", "text",
    "answer", "feedback_text", "reason", "summary", "title", "name", "match_pattern",
    # code and errors
    "code", "reasoning_content", "error_message",
    # URLs, which the remote file inclusion signatures match on an address
    "api_base", "base_url", "server_url", "url", "api_url",
    # secrets, whose random symbols the injection signatures match
    "password", "api_key", "client_secret", "access_token", "bot_token",
    "app_token", "user_token", "token", "api_secret",
    # the Google sign-in callback carries userinfo.profile here
    "scope",
  ]

  # A nested JSON key is reached only through the key it sits under, so whole
  # free-form objects are named by prefix.
  default_uninspected_field_prefixes = [
    "connector_specific_config", "credential_json", "definition", "custom_config",
    "new_custom_config", "existing_custom_config", "connection_headers", "config", "environment",
  ]

  # The names cover query string and body parameters, and the top-level keys
  # of a JSON body.
  uninspected_params = concat(
    [for f in concat(local.default_uninspected_fields, var.extra_uninspected_fields) : { operator = "EQUALS", value = f }],
    [for f in concat(local.default_uninspected_field_prefixes, var.extra_uninspected_field_prefixes) : { operator = "STARTS_WITH", value = f }],
  )

  # Cloud Armor does not parse a multipart body. It reads the file content as
  # parameter names, which no exclusion covers, so the content rule sets skip
  # an upload. The method check keeps the header from exempting a GET.
  multipart_guard = "!(request.method.matches('POST|PUT|PATCH') && request.headers['content-type'].lower().startsWith('multipart/form-data')) && "

  # One exclusion per content rule set, for every signature in it.
  waf_exclusions = {
    for k in local.waf_rule_keys : k => contains(local.untuned_rule_sets, k) ? [] : [{
      rule_set     = "${k}-${var.crs_version}-stable"
      query_params = local.uninspected_params
    }]
  }

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
      exclusions    = []
    }],
    length(var.allowed_ip_cidrs) > 0 ? [{
      priority      = 2000
      action        = "deny(403)"
      description   = "Requests from outside the allowlist"
      preview       = false
      src_ip_ranges = null
      expression    = "!(${join(" || ", [for c in var.allowed_ip_cidrs : "inIpRange(origin.ip, '${c}')"])})"
      rate_limit    = null
      exclusions    = []
    }] : [],
    [for i, chunk in local.country_chunks : {
      priority      = 2100 + i
      action        = "deny(403)"
      description   = "Blocked countries"
      preview       = false
      src_ip_ranges = null
      expression    = join(" || ", [for c in chunk : "origin.region_code == '${c}'"])
      rate_limit    = null
      exclusions    = []
    }],
    [for i, k in local.waf_rule_keys : {
      priority      = 3000 + i
      action        = "deny(403)"
      description   = "OWASP CRS ${k}"
      preview       = coalesce(var.preconfigured_rules[k].preview, var.preview)
      src_ip_ranges = null
      expression    = "${contains(local.untuned_rule_sets, k) ? "" : local.multipart_guard}${local.waf_expressions[k]}"
      rate_limit    = null
      exclusions    = local.waf_exclusions[k]
    }],
    [for i, chunk in local.exempt_chunks : {
      priority      = 4000 + i
      action        = "allow"
      description   = "Rate limit exempt address ranges"
      preview       = false
      src_ip_ranges = chunk
      expression    = null
      rate_limit    = null
      exclusions    = []
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
      exclusions    = []
    }],
    [{
      priority      = 5100
      action        = "throttle"
      description   = "Global rate limit per client address"
      preview       = var.preview
      src_ip_ranges = ["*"]
      expression    = null
      rate_limit    = { count = var.rate_limit_threshold }
      exclusions    = []
    }],
    [{
      priority      = 2147483647
      action        = "allow"
      description   = "Default rule"
      preview       = false
      src_ip_ranges = ["*"]
      expression    = null
      rate_limit    = null
      exclusions    = []
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

      dynamic "preconfigured_waf_config" {
        for_each = length(rule.value.exclusions) > 0 ? [rule.value.exclusions] : []
        content {
          dynamic "exclusion" {
            for_each = preconfigured_waf_config.value
            content {
              target_rule_set = exclusion.value.rule_set

              dynamic "request_query_param" {
                for_each = exclusion.value.query_params
                content {
                  operator = request_query_param.value.operator
                  value    = request_query_param.value.value
                }
              }
            }
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
