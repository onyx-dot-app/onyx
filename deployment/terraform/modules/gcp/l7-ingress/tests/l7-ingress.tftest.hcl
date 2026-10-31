# Plans the module against a mocked provider, so these run without a GCP
# project or credentials. Run with `terraform test` from the module directory.

mock_provider "google" {}

variables {
  name       = "onyx-prod"
  project_id = "example-project"
  domains    = ["onyx.example.com"]
}

run "defaults_build_an_external_ipv4_address_and_a_certificate_map" {
  command = plan

  assert {
    condition     = google_compute_global_address.this.name == "onyx-prod-l7"
    error_message = "The address should be named <name>-l7."
  }

  assert {
    condition     = google_compute_global_address.this.address_type == "EXTERNAL" && google_compute_global_address.this.ip_version == "IPV4"
    error_message = "A global external Application Load Balancer needs an external IPv4 address."
  }

  assert {
    condition     = google_certificate_manager_certificate_map.this.name == "onyx-prod-l7"
    error_message = "The certificate map should be named <name>-l7."
  }

  assert {
    condition     = output.address_name == "onyx-prod-l7" && output.certificate_map_name == "onyx-prod-l7"
    error_message = "The Gateway names the address and the map, so the outputs must carry them."
  }
}

run "each_domain_gets_an_authorization_a_certificate_and_a_map_entry" {
  command = plan

  variables {
    domains = ["onyx.example.com", "chat.example.org"]
  }

  assert {
    condition = alltrue([
      length(google_certificate_manager_dns_authorization.this) == 2,
      length(google_certificate_manager_certificate.this) == 2,
      length(google_certificate_manager_certificate_map_entry.this) == 2,
    ])
    error_message = "Two domains need two of each per-domain resource."
  }

  assert {
    condition = alltrue([
      for d, a in google_certificate_manager_dns_authorization.this :
      a.domain == d && a.location == "global" && a.type == "FIXED_RECORD"
    ])
    error_message = "Each authorization must be global and cover its own domain."
  }

  assert {
    condition = alltrue([
      for d, c in google_certificate_manager_certificate.this :
      one(c.managed).domains == tolist([d]) && c.scope == "DEFAULT" && c.location == "global"
    ])
    error_message = "Each certificate must be a global managed certificate for its own domain only."
  }

  assert {
    condition = alltrue([
      for d, e in google_certificate_manager_certificate_map_entry.this :
      e.hostname == d && e.map == "onyx-prod-l7"
    ])
    error_message = "Each map entry must select its domain by SNI hostname in the module's map."
  }
}

run "names_fit_certificate_manager_and_depend_on_the_domain_only" {
  command = plan

  variables {
    domains = ["onyx.example.com", "chat.example.org"]
  }

  assert {
    condition = alltrue([
      for a in google_certificate_manager_dns_authorization.this :
      can(regex("^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$", a.name))
    ])
    error_message = "Per-domain names must fit 63 characters with no dots."
  }

  # A name keyed on list position would change when another domain is added,
  # and the certificate would be replaced and serve nothing until reissued.
  assert {
    condition     = google_certificate_manager_certificate.this["onyx.example.com"].name == "onyx-prod-l7-${substr(sha1("onyx.example.com"), 0, 8)}"
    error_message = "A per-domain name must come from its domain alone."
  }
}

run "deletion_protection_guards_the_address_and_the_authorizations" {
  command = plan

  assert {
    condition     = google_compute_global_address.this.deletion_policy == "PREVENT"
    error_message = "A lost address means a DNS change, so it should be protected by default."
  }

  assert {
    condition     = alltrue([for a in google_certificate_manager_dns_authorization.this : a.deletion_policy == "PREVENT"])
    error_message = "A recreated authorization can need a new CNAME, so it should be protected by default."
  }
}

run "deletion_protection_can_be_turned_off" {
  command = plan

  variables {
    deletion_protection = false
  }

  assert {
    condition = google_compute_global_address.this.deletion_policy == "DELETE" && alltrue([
      for a in google_certificate_manager_dns_authorization.this : a.deletion_policy == "DELETE"
    ])
    error_message = "Turning off deletion protection should let Terraform delete the address and the authorizations."
  }
}

run "labels_reach_every_resource" {
  command = plan

  variables {
    labels = { env = "prod" }
  }

  assert {
    condition = alltrue(concat(
      [google_compute_global_address.this.labels == tomap({ env = "prod" })],
      [google_certificate_manager_certificate_map.this.labels == tomap({ env = "prod" })],
      [for a in google_certificate_manager_dns_authorization.this : a.labels == tomap({ env = "prod" })],
      [for c in google_certificate_manager_certificate.this : c.labels == tomap({ env = "prod" })],
      [for e in google_certificate_manager_certificate_map_entry.this : e.labels == tomap({ env = "prod" })],
    ))
    error_message = "Labels should reach the address, map, authorizations, certificates and map entries."
  }
}

run "the_dns_records_are_published_per_domain" {
  command = plan

  override_resource {
    target          = google_certificate_manager_dns_authorization.this
    override_during = plan
    values = {
      dns_resource_record = [{
        name = "_acme-challenge.onyx.example.com."
        type = "CNAME"
        data = "0123abcd.1.authorize.certificatemanager.goog."
      }]
    }
  }

  assert {
    condition = output.dns_authorization_records == {
      "onyx.example.com" = {
        name = "_acme-challenge.onyx.example.com."
        type = "CNAME"
        data = "0123abcd.1.authorize.certificatemanager.goog."
      }
    }
    error_message = "Each domain should map to the name, type and data of the record a person adds at the DNS provider."
  }
}

run "rejects_an_empty_domain_list" {
  command = plan

  variables {
    domains = []
  }

  expect_failures = [var.domains]
}

run "rejects_a_wildcard_domain" {
  command = plan

  variables {
    domains = ["*.example.com"]
  }

  expect_failures = [var.domains]
}

run "rejects_an_uppercase_domain" {
  command = plan

  variables {
    domains = ["Onyx.Example.com"]
  }

  expect_failures = [var.domains]
}

run "rejects_a_trailing_dot" {
  command = plan

  variables {
    domains = ["onyx.example.com."]
  }

  expect_failures = [var.domains]
}

run "rejects_a_bare_hostname" {
  command = plan

  variables {
    domains = ["onyx"]
  }

  expect_failures = [var.domains]
}

run "rejects_an_ip_address" {
  command = plan

  variables {
    domains = ["203.0.113.10"]
  }

  expect_failures = [var.domains]
}

run "rejects_a_repeated_domain" {
  command = plan

  variables {
    domains = ["onyx.example.com", "onyx.example.com"]
  }

  expect_failures = [var.domains]
}

run "rejects_a_name_too_long_for_the_suffix" {
  command = plan

  variables {
    name = "a${join("", [for i in range(51) : "b"])}"
  }

  expect_failures = [var.name]
}

run "rejects_an_uppercase_label" {
  command = plan

  variables {
    labels = { Env = "prod" }
  }

  expect_failures = [var.labels]
}

run "rejects_a_malformed_project_id" {
  command = plan

  variables {
    project_id = "Example_Project"
  }

  expect_failures = [var.project_id]
}
