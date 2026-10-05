# Plans the module against a mocked provider, so these run without a Google
# Cloud project or credentials. Run with `terraform test` from the module directory.

mock_provider "google" {}

variables {
  name       = "onyx"
  project_id = "example-project"
}

run "defaults_are_secure" {
  command = plan

  assert {
    condition     = google_compute_security_policy.this.name == "onyx-waf"
    error_message = "The policy should be named <name>-waf, like the Azure module."
  }

  assert {
    condition     = google_compute_security_policy.this.type == "CLOUD_ARMOR"
    error_message = "A backend security policy is the type that runs preconfigured WAF rules."
  }

  assert {
    condition     = google_compute_security_policy.this.deletion_policy == "PREVENT"
    error_message = "Deletion protection should be on by default."
  }

  assert {
    condition     = one(google_compute_security_policy.this.advanced_options_config).json_parsing == "STANDARD"
    error_message = "Without JSON parsing the WAF reads a JSON body as one opaque string."
  }

  assert {
    condition     = one(google_compute_security_policy.this.advanced_options_config).request_body_inspection_size == "64KB"
    error_message = "The WAF should inspect as much of the body as Cloud Armor allows."
  }

  assert {
    condition     = one(one(google_compute_security_policy.this.adaptive_protection_config).layer_7_ddos_defense_config).enable == true
    error_message = "Adaptive Protection should be on by default."
  }

  assert {
    condition     = length(google_compute_security_policy.this.rule) == 11
    error_message = "Defaults should give eight WAF rules, two rate limits and the default rule."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : r.action if r.priority == 2147483647
    ]) == "allow"
    error_message = "The default rule allows, like the AWS default_action."
  }
}

run "defaults_enforce_the_owasp_rule_sets_at_sensitivity_one" {
  command = plan

  assert {
    condition = length([
      for r in google_compute_security_policy.this.rule : r if r.priority >= 3000 && r.priority < 4000
    ]) == 8
    error_message = "All eight default rule sets should become rules."
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule :
      r.action == "deny(403)" && r.preview == false if r.priority >= 3000 && r.priority < 4000
    ])
    error_message = "WAF rules should block by default, not only log."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule :
      one(r.match).expr[0].expression if r.description == "OWASP CRS sqli"
    ]) == "!request.headers['content-type'].lower().startsWith('multipart/form-data') && evaluatePreconfiguredWaf('sqli-v33-stable', {'sensitivity': 1})"
    error_message = "The SQLi rule should evaluate sqli-v33-stable at sensitivity 1."
  }
}

run "content_rule_sets_skip_multipart_uploads_only" {
  command = plan

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule :
      startswith(one(r.match).expr[0].expression, "!request.headers['content-type'].lower().startsWith('multipart/form-data') && evaluatePreconfiguredWaf(")
      if startswith(r.description, "OWASP CRS ") && !contains(["methodenforcement", "scannerdetection", "sessionfixation"], trimprefix(r.description, "OWASP CRS "))
    ])
    error_message = "Rule sets that read field values should skip multipart uploads, whose file content Cloud Armor reads as parameter names."
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule :
      startswith(one(r.match).expr[0].expression, "evaluatePreconfiguredWaf(")
      if contains(["methodenforcement", "scannerdetection", "sessionfixation"], trimprefix(r.description, "OWASP CRS "))
    ])
    error_message = "The untuned rule sets should check every request."
  }
}

run "content_rule_sets_do_not_read_the_free_text_fields" {
  command = plan

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule :
      length(one(r.preconfigured_waf_config).exclusion) == 1
      && one(one(r.preconfigured_waf_config).exclusion).target_rule_set == "${trimprefix(r.description, "OWASP CRS ")}-v33-stable"
      && one(one(r.preconfigured_waf_config).exclusion).target_rule_ids == null
      && alltrue([for p in one(one(r.preconfigured_waf_config).exclusion).request_query_param : contains(["EQUALS", "STARTS_WITH"], p.operator)])
      && length(one(one(r.preconfigured_waf_config).exclusion).request_query_param) > 30
      if startswith(r.description, "OWASP CRS ") && !contains(["methodenforcement", "scannerdetection", "sessionfixation"], trimprefix(r.description, "OWASP CRS "))
    ])
    error_message = "Every content rule set should carry one exclusion for every signature, naming each uninspected field and prefix."
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule : length(r.preconfigured_waf_config) == 0
      if !startswith(r.description, "OWASP CRS ") || contains(["methodenforcement", "scannerdetection", "sessionfixation"], trimprefix(r.description, "OWASP CRS "))
    ])
    error_message = "Only the content rule sets should carry exclusions."
  }

  assert {
    condition = alltrue([
      for f in [
        { operator = "EQUALS", value = "message" },
        { operator = "EQUALS", value = "password" },
        { operator = "EQUALS", value = "api_base" },
        { operator = "EQUALS", value = "scope" },
        { operator = "EQUALS", value = "query" },
        { operator = "STARTS_WITH", value = "connector_specific_config" },
      ] :
      contains(one([
        for r in google_compute_security_policy.this.rule :
        one(one(r.preconfigured_waf_config).exclusion).request_query_param if r.description == "OWASP CRS sqli"
      ]), f)
    ])
    error_message = "The defaults should hold the fields measured to trip the signatures: chat text, passwords, URLs, the sign-in scope, search text, and the nested connector configuration."
  }
}

run "extra_fields_join_the_defaults" {
  command = plan

  variables {
    extra_uninspected_fields         = ["comment"]
    extra_uninspected_field_prefixes = ["custom_config"]
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule :
      contains(one(one(r.preconfigured_waf_config).exclusion).request_query_param, { operator = "EQUALS", value = "comment" })
      && contains(one(one(r.preconfigured_waf_config).exclusion).request_query_param, { operator = "STARTS_WITH", value = "custom_config" })
      && contains(one(one(r.preconfigured_waf_config).exclusion).request_query_param, { operator = "EQUALS", value = "message" })
      if startswith(r.description, "OWASP CRS ") && !contains(["methodenforcement", "scannerdetection", "sessionfixation"], trimprefix(r.description, "OWASP CRS "))
    ])
    error_message = "Caller extras should be added to the defaults, not replace them."
  }
}

run "a_rule_set_outside_the_defaults_is_tuned_too" {
  command = plan

  variables {
    crs_version         = "v422"
    preconfigured_rules = { generic = {} }
  }

  assert {
    condition = startswith(one([
      for r in google_compute_security_policy.this.rule : one(r.match).expr[0].expression if r.description == "OWASP CRS generic"
    ]), "!request.headers['content-type'].lower().startsWith('multipart/form-data') && evaluatePreconfiguredWaf('generic-v422-stable'")
    error_message = "Every rule set outside the untuned three should skip multipart uploads."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule :
      one(one(r.preconfigured_waf_config).exclusion).target_rule_set if r.description == "OWASP CRS generic"
    ]) == "generic-v422-stable"
    error_message = "The exclusion should name the rule set of the chosen CRS version."
  }
}

run "rejects_a_field_name_that_is_not_a_parameter_name" {
  command = plan

  variables {
    extra_uninspected_fields = ["a b"]
  }

  expect_failures = [var.extra_uninspected_fields]
}


run "rate_limits_mirror_the_aws_defaults" {
  command = plan

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : (
        one(r.rate_limit_options).rate_limit_threshold[0].count == 2000 &&
        one(r.rate_limit_options).rate_limit_threshold[0].interval_sec == 300 &&
        one(r.rate_limit_options).enforce_on_key == "IP" &&
        one(r.rate_limit_options).exceed_action == "deny(429)"
      ) if r.priority == 5100
    ])
    error_message = "The global limit should be 2000 requests per 5 minutes per address, like the AWS module."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : one(r.rate_limit_options).rate_limit_threshold[0].count if r.priority == 5000
    ]) == 1000
    error_message = "The API limit should be 1000 requests per 5 minutes, like the AWS and Azure modules."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : one(r.match).expr[0].expression if r.priority == 5000
    ]) == "request.path.startsWith('/api')"
    error_message = "The API limit should only match the API path."
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule : r.action == "throttle" if length(r.rate_limit_options) > 0
    ])
    error_message = "Rate limits should throttle, not ban."
  }
}

run "an_allowlist_denies_everything_outside_it_before_the_waf" {
  command = plan

  variables {
    allowed_ip_cidrs = ["203.0.113.0/24", "2001:db8::/32"]
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : one(r.match).expr[0].expression if r.priority == 2000
    ]) == "!(inIpRange(origin.ip, '203.0.113.0/24') || inIpRange(origin.ip, '2001:db8::/32'))"
    error_message = "The allowlist rule must deny addresses that are NOT on the list."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : r.action if r.priority == 2000
    ]) == "deny(403)"
    error_message = "The allowlist rule must deny, not allow. An allow would stop evaluation and skip the WAF rules."
  }
}

run "blocked_ranges_are_split_ten_per_rule" {
  command = plan

  variables {
    blocked_ip_cidrs = [for i in range(12) : "198.51.100.${i}/32"]
  }

  assert {
    condition = length([
      for r in google_compute_security_policy.this.rule : r if r.priority >= 1000 && r.priority < 2000
    ]) == 2
    error_message = "Twelve ranges need two rules, because a rule matches at most 10."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : length(one(r.match).config[0].src_ip_ranges) if r.priority == 1000
    ]) == 10
    error_message = "The first chunk should carry the first 10 ranges."
  }
}

run "exempt_ranges_skip_the_rate_limits_but_not_the_waf" {
  command = plan

  variables {
    rate_limit_exempt_ip_cidrs = ["203.0.113.0/24"]
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : r.action if r.priority == 4000
    ]) == "allow"
    error_message = "Exempt ranges get an allow rule."
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule : r.priority < 4000 if startswith(r.description, "OWASP CRS")
    ])
    error_message = "The exemption must come after every WAF rule, or exempt addresses would skip the WAF too."
  }
}

run "geo_blocking_adds_a_rule" {
  command = plan

  variables {
    geo_restriction_countries = ["KP", "IR"]
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : one(r.match).expr[0].expression if r.priority == 2100
    ]) == "origin.region_code == 'KP' || origin.region_code == 'IR'"
    error_message = "Country blocking should match on origin.region_code."
  }
}

run "preview_logs_waf_and_rate_limits_but_keeps_ip_rules" {
  command = plan

  variables {
    preview          = true
    blocked_ip_cidrs = ["198.51.100.0/24"]
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule : r.preview if r.priority >= 3000 && r.priority < 6000
    ])
    error_message = "Preview should cover the WAF rules and both rate limits."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : r.preview if r.priority == 1000
    ]) == false
    error_message = "Blocked ranges were listed on purpose and should still be enforced."
  }
}

run "per_rule_settings_override_the_module_wide_ones" {
  command = plan

  variables {
    preconfigured_rules = {
      sqli = {
        sensitivity      = 2
        preview          = true
        opt_out_rule_ids = ["owasp-crs-v030301-id942421-sqli", "owasp-crs-v030301-id942432-sqli"]
      }
      xss = {}
    }
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : one(r.match).expr[0].expression if r.description == "OWASP CRS sqli"
    ]) == "!request.headers['content-type'].lower().startsWith('multipart/form-data') && evaluatePreconfiguredWaf('sqli-v33-stable', {'sensitivity': 2, 'opt_out_rule_ids': ['owasp-crs-v030301-id942421-sqli', 'owasp-crs-v030301-id942432-sqli']})"
    error_message = "The SQLi rule should carry its own sensitivity and opt-outs."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : r.preview if r.description == "OWASP CRS sqli"
    ]) == true
    error_message = "A per-rule preview should override the module-wide value."
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.this.rule : r.preview if r.description == "OWASP CRS xss"
    ]) == false
    error_message = "A rule without its own preview should use the module-wide value."
  }
}

run "crs_422_uses_its_own_rule_names" {
  command = plan

  variables {
    crs_version = "v422"
    preconfigured_rules = {
      generic = {}
      sqli    = { opt_out_rule_ids = ["owasp-crs-v042200-id942421-sqli"] }
    }
  }

  assert {
    condition = alltrue([
      for r in google_compute_security_policy.this.rule :
      strcontains(one(r.match).expr[0].expression, "-v422-stable") if startswith(r.description, "OWASP CRS")
    ])
    error_message = "Every WAF rule should evaluate the v422 rule set."
  }
}

run "optional_protections_can_be_turned_off" {
  command = plan

  variables {
    deletion_protection         = false
    adaptive_protection_enabled = false
    labels                      = { env = "dev" }
  }

  assert {
    condition     = google_compute_security_policy.this.deletion_policy == "DELETE"
    error_message = "Turning off deletion protection should let Terraform delete the policy."
  }

  assert {
    condition     = one(one(google_compute_security_policy.this.adaptive_protection_config).layer_7_ddos_defense_config).enable == false
    error_message = "Adaptive Protection should follow its toggle."
  }

  assert {
    condition     = google_compute_security_policy.this.labels == tomap({ env = "dev" })
    error_message = "Labels should reach the policy."
  }
}

run "rejects_a_rule_set_the_crs_version_does_not_carry" {
  command = plan

  # nodejs exists in CRS 3.3 only.
  variables {
    crs_version         = "v422"
    preconfigured_rules = { nodejs = {} }
  }

  expect_failures = [var.preconfigured_rules]
}

run "rejects_a_misspelled_rule_set" {
  command = plan

  variables {
    preconfigured_rules = { sql = {} }
  }

  expect_failures = [var.preconfigured_rules]
}

run "rejects_a_rule_sensitivity_out_of_range" {
  command = plan

  variables {
    preconfigured_rules = { sqli = { sensitivity = 0 } }
  }

  expect_failures = [var.preconfigured_rules]
}

run "rejects_an_opt_out_from_another_rule_set" {
  command = plan

  # Without this the opt-out matches nothing and the signature keeps firing.
  variables {
    preconfigured_rules = { sqli = { opt_out_rule_ids = ["owasp-crs-v030301-id941100-xss"] } }
  }

  expect_failures = [var.preconfigured_rules]
}

run "rejects_an_opt_out_from_another_crs_version" {
  command = plan

  variables {
    preconfigured_rules = { sqli = { opt_out_rule_ids = ["owasp-crs-v042200-id942421-sqli"] } }
  }

  expect_failures = [var.preconfigured_rules]
}

run "rejects_an_expression_over_the_cloud_armor_limit" {
  command = plan

  variables {
    preconfigured_rules = {
      sqli = { opt_out_rule_ids = [for i in range(40) : format("owasp-crs-v030301-id%06d-sqli", 942100 + i)] }
    }
  }

  expect_failures = [google_compute_security_policy.this]
}

run "rejects_a_global_sensitivity_out_of_range" {
  command = plan

  variables {
    sensitivity = 5
  }

  expect_failures = [var.sensitivity]
}

run "rejects_more_allowlist_ranges_than_one_expression_holds" {
  command = plan

  variables {
    allowed_ip_cidrs = [for i in range(11) : "198.51.100.${i}/32"]
  }

  expect_failures = [var.allowed_ip_cidrs]
}

run "rejects_a_range_that_is_not_a_cidr" {
  command = plan

  variables {
    blocked_ip_cidrs = ["198.51.100.1"]
  }

  expect_failures = [var.blocked_ip_cidrs]
}

run "rejects_a_rate_limit_interval_cloud_armor_does_not_have" {
  command = plan

  variables {
    rate_limit_interval_sec = 100
  }

  expect_failures = [var.rate_limit_interval_sec]
}

run "rejects_a_zero_rate_limit" {
  command = plan

  variables {
    rate_limit_threshold = 0
  }

  expect_failures = [var.rate_limit_threshold]
}

run "rejects_an_api_path_that_would_break_the_expression" {
  command = plan

  variables {
    api_path_prefix = "/api') || true || ('"
  }

  expect_failures = [var.api_path_prefix]
}

run "rejects_a_name_too_long_for_the_suffix" {
  command = plan

  variables {
    name = "a${join("", [for i in range(59) : "b"])}"
  }

  expect_failures = [var.name]
}

run "rejects_an_uppercase_label" {
  command = plan

  variables {
    labels = { Env = "dev" }
  }

  expect_failures = [var.labels]
}

run "rejects_a_country_code_that_is_not_one" {
  command = plan

  variables {
    geo_restriction_countries = ["Korea"]
  }

  expect_failures = [var.geo_restriction_countries]
}
