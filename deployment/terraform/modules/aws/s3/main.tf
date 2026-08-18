# When this module was promoted to the shared template (#399), the bucket
# resource was renamed `bucket` -> `this` WITHOUT a moved block. Consumers that
# hadn't re-applied since then still have `aws_s3_bucket.bucket` in state, so a
# plan reads the rename as destroy-old + create-new — i.e. it would delete and
# recreate the bucket (data loss). This relabels it in state instead. It's a
# no-op for consumers already on the new address (the `from` isn't in their
# state), and applies to every instance of this module (module.s3, s3_upload).
moved {
  from = aws_s3_bucket.bucket
  to   = aws_s3_bucket.this
}

# The bucket policy was renamed `bucket_policy` -> `anonymous_read` and made
# conditional. Callers that set s3_vpc_endpoint_id (previously a required
# input) still get a policy, so the target instance exists for them. Relabelling
# keeps the upgrade an in-place policy update instead of destroy + create.
moved {
  from = aws_s3_bucket_policy.bucket_policy
  to   = aws_s3_bucket_policy.anonymous_read[0]
}

resource "aws_s3_bucket" "this" {
  bucket        = var.bucket_name
  force_destroy = var.force_destroy
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id
  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      # KMS encryption requires SigV4 signing, which anonymous requests can't provide
      sse_algorithm     = var.allow_anonymous_read ? "AES256" : "aws:kms"
      kms_master_key_id = var.allow_anonymous_read ? null : var.kms_key_id
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = var.block_public_policy != null ? var.block_public_policy : (var.allow_anonymous_read ? false : true)
  ignore_public_acls      = true
  restrict_public_buckets = var.restrict_public_buckets != null ? var.restrict_public_buckets : (var.allow_anonymous_read ? false : true)
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "noncurrent-version-expiration"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_expiration_days
    }
  }

  dynamic "rule" {
    for_each = var.expiration_days > 0 ? [1] : []
    content {
      id     = "object-expiration"
      status = "Enabled"

      expiration {
        days = var.expiration_days
      }
    }
  }

  dynamic "rule" {
    for_each = var.transition_to_ia ? [1] : []
    content {
      id     = "transition-to-ia"
      status = "Enabled"

      transition {
        days          = var.transition_to_ia_days
        storage_class = "INTELLIGENT_TIERING"
      }
    }
  }
}

locals {
  needs_bucket_policy = (var.allow_anonymous_read && (length(var.allowed_vpc_ids) > 0 || length(var.allowed_source_ips) > 0)) || length(var.s3_vpc_endpoint_id) > 0
}

data "aws_iam_policy_document" "anonymous_read" {
  count = local.needs_bucket_policy ? 1 : 0

  # Allow anonymous GetObject from allowed IPs
  dynamic "statement" {
    for_each = var.allow_anonymous_read && length(var.allowed_source_ips) > 0 ? [1] : []
    content {
      sid     = "AllowAnonymousReadFromAllowedIps"
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [
        "${aws_s3_bucket.this.arn}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "IpAddress"
        variable = "aws:SourceIp"
        values   = var.allowed_source_ips
      }
    }
  }

  # Allow anonymous GetObject from allowed VPCs (requires VPC endpoint)
  dynamic "statement" {
    for_each = var.allow_anonymous_read && length(var.allowed_vpc_ids) > 0 ? [1] : []
    content {
      sid     = "AllowAnonymousReadFromAllowedVpcs"
      effect  = "Allow"
      actions = ["s3:GetObject"]
      resources = [
        "${aws_s3_bucket.this.arn}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "StringEquals"
        variable = "aws:SourceVpc"
        values   = var.allowed_vpc_ids
      }
    }
  }

  # Allow GetObject + ListBucket via a specific S3 gateway VPC endpoint
  dynamic "statement" {
    for_each = length(var.s3_vpc_endpoint_id) > 0 ? [1] : []
    content {
      sid     = "AllowAccessViaVPCE"
      effect  = "Allow"
      actions = ["s3:GetObject", "s3:ListBucket"]
      resources = [
        aws_s3_bucket.this.arn,
        "${aws_s3_bucket.this.arn}/*"
      ]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
      condition {
        test     = "StringEquals"
        variable = "aws:SourceVpce"
        values   = [var.s3_vpc_endpoint_id]
      }
    }
  }
}

resource "aws_s3_bucket_policy" "anonymous_read" {
  count  = local.needs_bucket_policy ? 1 : 0
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.anonymous_read[0].json
}
