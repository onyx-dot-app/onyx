locals {
  # Onyx calls get_bucket on api_server startup (FileStore.initialize) and
  # crashes if that is forbidden. objectAdmin covers every object operation but
  # not storage.buckets.get, so each member also gets the narrowest role that
  # carries it.
  member_roles = toset(["roles/storage.objectAdmin", "roles/storage.legacyBucketReader"])

  # Members are caller-supplied strings known at plan time, so they are safe as
  # for_each keys. Keying on an apply-time value instead (a service account
  # email created in the same run) fails with "Invalid for_each argument",
  # which is what forced the Azure modules onto a static key set.
  member_bindings = {
    for pair in setproduct(var.object_admin_members, local.member_roles) :
    "${pair[1]}|${pair[0]}" => { member = pair[0], role = pair[1] }
  }
}

resource "google_storage_bucket" "this" {
  name     = var.name
  project  = var.project_id
  location = upper(var.location)

  storage_class = var.storage_class
  force_destroy = var.force_destroy

  # PREVENT is enforced from state, so a destroy fails before any API call.
  deletion_policy = var.deletion_protection ? "PREVENT" : "DELETE"

  # IAM only, no ACLs, and no allUsers / allAuthenticatedUsers grants can take
  # effect even if one is added later outside Terraform.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  labels = var.labels

  versioning {
    enabled = var.versioning_enabled
  }

  dynamic "encryption" {
    for_each = var.kms_key_name == null ? [] : [1]
    content {
      default_kms_key_name = var.kms_key_name
    }
  }

  dynamic "lifecycle_rule" {
    for_each = var.versioning_enabled ? [1] : []
    content {
      action {
        type = "Delete"
      }
      condition {
        days_since_noncurrent_time = var.noncurrent_version_retention_days
        with_state                 = "ARCHIVED"
      }
    }
  }

  # GCS has no Intelligent-Tiering, so this is a plain age-based move.
  # matches_storage_class keeps the rule from re-firing on objects it already
  # moved.
  dynamic "lifecycle_rule" {
    for_each = var.nearline_after_days == null ? [] : [1]
    content {
      action {
        type          = "SetStorageClass"
        storage_class = "NEARLINE"
      }
      condition {
        age                   = var.nearline_after_days
        matches_storage_class = ["STANDARD"]
      }
    }
  }
}

resource "google_storage_bucket_iam_member" "members" {
  for_each = local.member_bindings

  bucket = google_storage_bucket.this.name
  role   = each.value.role
  member = each.value.member
}
