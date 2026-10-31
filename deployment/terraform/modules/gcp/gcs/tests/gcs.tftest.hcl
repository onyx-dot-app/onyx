# Plans the module against a mocked provider, so these run without a GCP
# project or credentials. Run with `terraform test` from the module directory.

mock_provider "google" {}

variables {
  name       = "onyx-file-store-prod"
  project_id = "onyx-example-project"
  location   = "us-east1"
}

run "defaults_are_private_and_protected" {
  command = plan

  assert {
    condition     = google_storage_bucket.this.uniform_bucket_level_access == true
    error_message = "Access must be IAM-only, with no object ACLs."
  }

  assert {
    condition     = google_storage_bucket.this.public_access_prevention == "enforced"
    error_message = "The file store must never be servable publicly."
  }

  assert {
    condition     = google_storage_bucket.this.force_destroy == false
    error_message = "A destroy must not silently delete stored files."
  }

  assert {
    condition     = google_storage_bucket.this.deletion_policy == "PREVENT"
    error_message = "deletion_protection should default on."
  }

  assert {
    condition     = one(google_storage_bucket.this.versioning).enabled == true
    error_message = "Versioning should default on."
  }

  assert {
    condition     = length(google_storage_bucket.this.encryption) == 0
    error_message = "With no kms_key_name the bucket should use Google-managed keys."
  }

  assert {
    condition     = length(google_storage_bucket.this.soft_delete_policy) == 0
    error_message = "Soft delete should stay at the GCS default, so the module must not set it."
  }

  assert {
    condition     = google_storage_bucket.this.location == "US-EAST1"
    error_message = "Location should be upper-cased so a lowercase input does not cause a perpetual diff."
  }
}

run "default_lifecycle_expires_noncurrent_versions_only" {
  command = plan

  assert {
    condition     = length(google_storage_bucket.this.lifecycle_rule) == 1
    error_message = "Only the noncurrent-version rule should exist by default; the NEARLINE move is off."
  }

  assert {
    condition     = one(google_storage_bucket.this.lifecycle_rule[0].action).type == "Delete"
    error_message = "The default rule should delete old versions."
  }

  assert {
    condition     = one(google_storage_bucket.this.lifecycle_rule[0].condition).days_since_noncurrent_time == 30
    error_message = "Noncurrent versions should be kept 30 days by default."
  }
}

run "no_versioning_means_no_lifecycle_rules" {
  command = plan

  variables {
    versioning_enabled = false
  }

  assert {
    condition     = length(google_storage_bucket.this.lifecycle_rule) == 0
    error_message = "Without versioning there are no noncurrent versions to expire."
  }
}

run "nearline_adds_a_transition_rule" {
  command = plan

  variables {
    nearline_after_days = 60
  }

  assert {
    condition     = length(google_storage_bucket.this.lifecycle_rule) == 2
    error_message = "Setting nearline_after_days should add the transition rule."
  }

  assert {
    condition     = one(google_storage_bucket.this.lifecycle_rule[1].action).storage_class == "NEARLINE"
    error_message = "The transition rule should move objects to NEARLINE."
  }

  assert {
    condition     = one(google_storage_bucket.this.lifecycle_rule[1].condition).age == 60
    error_message = "The transition rule should use nearline_after_days as the object age."
  }

  assert {
    condition     = one(google_storage_bucket.this.lifecycle_rule[1].condition).matches_storage_class == tolist(["STANDARD"])
    error_message = "The transition rule should only match STANDARD objects."
  }
}

run "cmek_sets_the_default_key" {
  command = plan

  variables {
    kms_key_name = "projects/onyx-example-project/locations/us-east1/keyRings/onyx/cryptoKeys/file-store"
  }

  assert {
    condition     = one(google_storage_bucket.this.encryption).default_kms_key_name == "projects/onyx-example-project/locations/us-east1/keyRings/onyx/cryptoKeys/file-store"
    error_message = "kms_key_name should become the bucket's default key."
  }
}

run "deletion_protection_off_allows_delete" {
  command = plan

  variables {
    deletion_protection = false
  }

  assert {
    condition     = google_storage_bucket.this.deletion_policy == "DELETE"
    error_message = "Turning deletion_protection off should let Terraform delete the bucket."
  }
}

run "no_members_means_no_grants" {
  command = plan

  assert {
    condition     = length(google_storage_bucket_iam_member.members) == 0
    error_message = "No IAM grants should exist by default."
  }
}

run "each_member_can_use_the_bucket_as_onyx_does" {
  command = plan

  variables {
    object_admin_members = [
      "principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/onyx-example-project.svc.id.goog/subject/ns/onyx/sa/onyx-workload-access",
      "serviceAccount:onyx-backup@onyx-example-project.iam.gserviceaccount.com",
    ]
  }

  assert {
    condition     = length(google_storage_bucket_iam_member.members) == 4
    error_message = "Each member should get two grants."
  }

  assert {
    condition     = length([for g in google_storage_bucket_iam_member.members : g if g.role == "roles/storage.objectAdmin"]) == 2
    error_message = "Each member needs objectAdmin for the file store's object operations."
  }

  # objectAdmin lacks storage.buckets.get, which api_server startup needs.
  assert {
    condition     = length([for g in google_storage_bucket_iam_member.members : g if g.role == "roles/storage.legacyBucketReader"]) == 2
    error_message = "Each member needs storage.buckets.get, or FileStore.initialize() fails at startup."
  }
}

run "labels_reach_the_bucket" {
  command = plan

  variables {
    labels = { env = "prod", app = "onyx" }
  }

  assert {
    condition     = google_storage_bucket.this.labels == tomap({ env = "prod", app = "onyx" })
    error_message = "Caller labels should be set on the bucket."
  }
}

run "rejects_nearline_on_a_colder_default_class" {
  command = plan

  variables {
    storage_class       = "COLDLINE"
    nearline_after_days = 60
  }

  expect_failures = [var.nearline_after_days]
}

run "rejects_a_zero_nearline_age" {
  command = plan

  variables {
    nearline_after_days = 0
  }

  expect_failures = [var.nearline_after_days]
}

run "rejects_zero_noncurrent_retention" {
  command = plan

  variables {
    noncurrent_version_retention_days = 0
  }

  expect_failures = [var.noncurrent_version_retention_days]
}

run "rejects_an_unknown_storage_class" {
  command = plan

  variables {
    storage_class = "REGIONAL"
  }

  expect_failures = [var.storage_class]
}

run "rejects_an_uppercase_name" {
  command = plan

  variables {
    name = "Onyx-File-Store"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_that_is_too_short" {
  command = plan

  variables {
    name = "ab"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_that_is_too_long" {
  command = plan

  variables {
    name = "onyx-file-store-production-us-east1-with-a-very-long-suffix-abcd"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_ending_in_a_hyphen" {
  command = plan

  variables {
    name = "onyx-file-store-"
  }

  expect_failures = [var.name]
}

run "rejects_a_goog_prefix" {
  command = plan

  variables {
    name = "goog-onyx-files"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_containing_google" {
  command = plan

  variables {
    name = "onyx-google-files"
  }

  expect_failures = [var.name]
}

run "rejects_an_ip_address_name" {
  command = plan

  variables {
    name = "192.168.5.4"
  }

  expect_failures = [var.name]
}

run "rejects_a_dot_next_to_a_hyphen" {
  command = plan

  variables {
    name = "onyx.-files"
  }

  expect_failures = [var.name]
}

run "rejects_a_malformed_kms_key" {
  command = plan

  variables {
    kms_key_name = "file-store-key"
  }

  expect_failures = [var.kms_key_name]
}

run "rejects_a_public_member" {
  command = plan

  variables {
    object_admin_members = ["allUsers"]
  }

  expect_failures = [var.object_admin_members]
}

run "rejects_a_bare_email_member" {
  command = plan

  variables {
    object_admin_members = ["onyx@onyx-example-project.iam.gserviceaccount.com"]
  }

  expect_failures = [var.object_admin_members]
}

run "rejects_uppercase_labels" {
  command = plan

  variables {
    labels = { Env = "Prod" }
  }

  expect_failures = [var.labels]
}

run "rejects_a_malformed_project_id" {
  command = plan

  variables {
    project_id = "Onyx_Project"
  }

  expect_failures = [var.project_id]
}
