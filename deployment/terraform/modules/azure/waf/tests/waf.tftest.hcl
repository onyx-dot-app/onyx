# Plans the module against a mocked provider, so these run without an Azure
# subscription or credentials. Run with `terraform test` from the module directory.

mock_provider "azurerm" {}

variables {
  name                = "onyx"
  resource_group_name = "onyx-rg"
  location            = "eastus"
}

run "defaults_block_and_carry_both_rule_sets" {
  command = plan

  assert {
    condition     = one(azurerm_web_application_firewall_policy.this.policy_settings).mode == "Prevention"
    error_message = "The policy should block what it matches by default."
  }

  assert {
    condition     = length(one(azurerm_web_application_firewall_policy.this.managed_rules).managed_rule_set) == 2
    error_message = "OWASP plus the bot manager set should both be present by default."
  }

  assert {
    condition     = one(azurerm_web_application_firewall_policy.this.managed_rules).managed_rule_set[0].type == "OWASP"
    error_message = "The OWASP set covers what the AWS module gets from its common, known-bad-inputs and SQLi groups."
  }
}

run "only_the_two_rate_limits_exist_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_web_application_firewall_policy.this.custom_rules) == 2
    error_message = "With no allowlist and no geo blocking, only the two rate limits should exist."
  }

  assert {
    condition = alltrue([
      for r in azurerm_web_application_firewall_policy.this.custom_rules :
      r.rate_limit_duration == "FiveMins"
    ])
    error_message = "The AWS module counts requests per five minutes, so these should too."
  }

  assert {
    condition = alltrue([
      for r in azurerm_web_application_firewall_policy.this.custom_rules :
      r.group_rate_limit_by == "ClientAddr"
    ])
    error_message = "Rate limits should count per client address, matching the AWS aggregate key of IP."
  }
}

run "an_allowlist_blocks_everything_outside_it_first" {
  command = plan

  variables {
    allowed_ip_cidrs = ["203.0.113.0/24"]
  }

  assert {
    condition     = length(azurerm_web_application_firewall_policy.this.custom_rules) == 3
    error_message = "The allowlist rule should be added to the two rate limits."
  }

  assert {
    condition = one([
      for r in azurerm_web_application_firewall_policy.this.custom_rules :
      r.priority if r.name == "BlockRequestsOutsideAllowedIPs"
    ]) == 1
    error_message = "The allowlist must be evaluated before anything else."
  }

  assert {
    condition = one([
      for r in azurerm_web_application_firewall_policy.this.custom_rules :
      r.match_conditions[0].negation_condition if r.name == "BlockRequestsOutsideAllowedIPs"
    ]) == true
    error_message = "The rule blocks addresses that are NOT on the list, so the condition has to be negated."
  }
}

run "exempt_ranges_add_a_negated_condition_to_each_limit" {
  command = plan

  variables {
    rate_limit_exempt_ip_cidrs = ["203.0.113.0/24"]
  }

  assert {
    condition = alltrue([
      for r in azurerm_web_application_firewall_policy.this.custom_rules :
      length(r.match_conditions) == 2 if r.rule_type == "RateLimitRule"
    ])
    error_message = "Conditions are combined with AND, so the exemption is a second, negated condition on each limit."
  }
}

run "geo_blocking_adds_a_rule" {
  command = plan

  variables {
    geo_restriction_countries = ["KP"]
  }

  assert {
    condition = one([
      for r in azurerm_web_application_firewall_policy.this.custom_rules :
      r.match_conditions[0].operator if r.name == "BlockRestrictedCountries"
    ]) == "GeoMatch"
    error_message = "Country blocking uses the GeoMatch operator."
  }
}

run "detection_mode_stops_blocking" {
  command = plan

  variables {
    mode = "Detection"
  }

  assert {
    condition     = one(azurerm_web_application_firewall_policy.this.policy_settings).mode == "Detection"
    error_message = "Detection is the whole-policy equivalent of overriding every AWS managed rule to COUNT."
  }
}

run "bot_protection_can_be_dropped" {
  command = plan

  variables {
    enable_bot_protection = false
  }

  assert {
    condition     = length(one(azurerm_web_application_firewall_policy.this.managed_rules).managed_rule_set) == 1
    error_message = "Turning off bot protection should leave only the OWASP set."
  }
}

run "overrides_are_regrouped_under_their_rule_set" {
  command = plan

  variables {
    managed_rule_overrides = [
      { rule_group_name = "REQUEST-942-APPLICATION-ATTACK-SQLI", rule_id = "942100", action = "Log" },
      { rule_group_name = "REQUEST-942-APPLICATION-ATTACK-SQLI", rule_id = "942200", action = "Log" },
      { rule_group_name = "REQUEST-920-PROTOCOL-ENFORCEMENT", rule_id = "920300", enabled = false },
    ]
  }

  assert {
    condition     = length(one(azurerm_web_application_firewall_policy.this.managed_rules).managed_rule_set[0].rule_group_override) == 2
    error_message = "Three overrides across two groups should nest into two group overrides."
  }

  assert {
    condition = length(one([
      for g in one(azurerm_web_application_firewall_policy.this.managed_rules).managed_rule_set[0].rule_group_override :
      g.rule if g.rule_group_name == "REQUEST-942-APPLICATION-ATTACK-SQLI"
    ])) == 2
    error_message = "Both SQLi overrides should land in the same group."
  }
}

run "bot_rule_set_overrides_land_on_the_bot_rule_set" {
  command = plan

  variables {
    managed_rule_overrides = [
      { rule_group_name = "UnknownBots", rule_id = "300700", action = "Log", rule_set_type = "Microsoft_BotManagerRuleSet" },
    ]
  }

  assert {
    condition     = length(one(azurerm_web_application_firewall_policy.this.managed_rules).managed_rule_set[0].rule_group_override) == 0
    error_message = "A bot override must not be attached to the OWASP set."
  }

  assert {
    condition     = length(one(azurerm_web_application_firewall_policy.this.managed_rules).managed_rule_set[1].rule_group_override) == 1
    error_message = "The override belongs to the bot manager set."
  }
}

run "rejects_an_override_for_a_rule_set_that_does_not_exist" {
  command = plan

  variables {
    managed_rule_overrides = [
      { rule_group_name = "SomeGroup", rule_id = "1", action = "Log", rule_set_type = "OWASP_CRS" },
    ]
  }

  expect_failures = [var.managed_rule_overrides]
}

run "rejects_a_bot_override_when_bot_protection_is_off" {
  command = plan

  # Without this the override is silently dropped and the rule keeps doing
  # exactly what the caller meant to change.
  variables {
    enable_bot_protection = false
    managed_rule_overrides = [
      { rule_group_name = "UnknownBots", rule_id = "300700", action = "Log", rule_set_type = "Microsoft_BotManagerRuleSet" },
    ]
  }

  expect_failures = [var.managed_rule_overrides]
}

run "rejects_a_group_from_the_wrong_rule_set" {
  command = plan

  # UnknownBots belongs to the bot manager set, not to OWASP.
  variables {
    managed_rule_overrides = [
      { rule_group_name = "UnknownBots", rule_id = "300700", action = "Log", rule_set_type = "OWASP" },
    ]
  }

  expect_failures = [var.managed_rule_overrides]
}

run "rejects_a_misspelled_group_name" {
  command = plan

  variables {
    managed_rule_overrides = [
      { rule_group_name = "REQUEST-942-APPLICATION-ATTACK-SQL", rule_id = "942100", action = "Log" },
    ]
  }

  expect_failures = [var.managed_rule_overrides]
}

run "rejects_an_action_azure_does_not_have" {
  command = plan

  variables {
    managed_rule_overrides = [
      { rule_group_name = "REQUEST-942-APPLICATION-ATTACK-SQLI", rule_id = "942100", action = "Count" },
    ]
  }

  expect_failures = [var.managed_rule_overrides]
}

run "rejects_a_country_code_that_is_not_one" {
  command = plan

  variables {
    geo_restriction_countries = ["Korea"]
  }

  expect_failures = [var.geo_restriction_countries]
}

run "rejects_an_upload_limit_azure_would_reject" {
  command = plan

  variables {
    file_upload_limit_in_mb = 5000
  }

  expect_failures = [var.file_upload_limit_in_mb]
}
