# Plans the module against a mocked provider, so these run without an AWS
# account or credentials. Run with `terraform test` from the module directory.

mock_provider "aws" {
  override_data {
    target = data.aws_iam_policy_document.anonymous_read
    values = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  bucket_name = "onyx-file-store-prod"
}

run "defaults_create_no_key_and_keep_the_existing_rules" {
  command = plan

  assert {
    condition     = length(aws_kms_key.this) == 0 && length(aws_kms_alias.this) == 0
    error_message = "No KMS key should be created unless create_kms_key is set."
  }

  assert {
    condition     = toset([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r.id]) == toset(["noncurrent-version-expiration", "transition-to-ia"])
    error_message = "The default lifecycle rules must not change."
  }
}

run "a_dedicated_key_encrypts_and_expires_the_bucket" {
  command = plan

  variables {
    bucket_name                            = "onyx-sandbox-archive-prod"
    create_kms_key                         = true
    expiration_days                        = 30
    noncurrent_expiration_days             = 7
    abort_incomplete_multipart_upload_days = 7
    transition_to_ia                       = false
  }

  assert {
    condition     = aws_kms_key.this[0].enable_key_rotation == true
    error_message = "The dedicated key must rotate."
  }

  assert {
    condition     = aws_kms_alias.this[0].name == "alias/onyx-sandbox-archive-prod"
    error_message = "The alias should be named after the bucket."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default).sse_algorithm == "aws:kms"
    error_message = "The bucket must use SSE-KMS."
  }

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.this.rule).bucket_key_enabled == true
    error_message = "A dedicated key should use bucket keys."
  }

  assert {
    condition     = aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning must be on."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.this.block_public_acls &&
      aws_s3_bucket_public_access_block.this.block_public_policy &&
      aws_s3_bucket_public_access_block.this.ignore_public_acls &&
      aws_s3_bucket_public_access_block.this.restrict_public_buckets
    )
    error_message = "Every public access block setting must be on."
  }

  assert {
    condition     = one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "object-expiration"]).expiration[0].days == 30
    error_message = "Objects should expire after expiration_days."
  }

  assert {
    condition     = one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "noncurrent-version-expiration"]).noncurrent_version_expiration[0].noncurrent_days == 7
    error_message = "Noncurrent versions should expire after noncurrent_expiration_days."
  }

  assert {
    condition     = one([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "abort-incomplete-multipart-upload"]).abort_incomplete_multipart_upload[0].days_after_initiation == 7
    error_message = "Unfinished multipart uploads should be removed."
  }

  assert {
    condition     = length([for r in aws_s3_bucket_lifecycle_configuration.this.rule : r if r.id == "transition-to-ia"]) == 0
    error_message = "transition_to_ia = false should drop the Intelligent-Tiering rule."
  }
}

run "rejects_a_dedicated_key_with_a_supplied_key" {
  command = plan

  variables {
    create_kms_key = true
    kms_key_id     = "arn:aws:kms:us-east-1:111111111111:key/abc"
  }

  expect_failures = [var.create_kms_key]
}

run "rejects_a_dedicated_key_with_anonymous_read" {
  command = plan

  variables {
    create_kms_key       = true
    allow_anonymous_read = true
  }

  expect_failures = [var.create_kms_key]
}
