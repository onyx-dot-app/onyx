# Provisions the cloud-side prerequisites for the Craft sandbox feature on a
# single EKS cluster:
#   - S3 bucket (AES-256, public access blocked) for sandbox snapshots / file-sync
#   - IAM policy granting RW on that bucket
#   - IAM role assumable via IRSA by the sandbox-file-sync ServiceAccount
#
# Outputs (`role_arn`, `bucket_name`) wire into the Helm chart's
# `craft.sandboxFileSyncRoleArn` and `configMap.SANDBOX_S3_BUCKET` values.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  oidc_issuer    = trimprefix(var.cluster_oidc_issuer_url, "https://")
  primary_sub    = "system:serviceaccount:${var.sandbox_namespace}:${var.service_account_name}"
  trust_subjects = concat([local.primary_sub], var.extra_trust_subjects)

  role_name   = coalesce(var.role_name, "SandboxFileSyncRole-${var.cluster_name}")
  policy_name = coalesce(var.policy_name, "${var.cluster_name}-sandbox-s3-policy")
}

resource "aws_s3_bucket" "sandbox" {
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "sandbox" {
  bucket                  = aws_s3_bucket.sandbox.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sandbox" {
  bucket = aws_s3_bucket.sandbox.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Backstop against orphaned multipart-upload parts: aborts incomplete uploads
# after 7 days. Does not expire completed objects — sandbox-snapshot retention
# is a product decision and should be configured separately if/when needed.
resource "aws_s3_bucket_lifecycle_configuration" "sandbox" {
  bucket = aws_s3_bucket.sandbox.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_iam_policy" "sandbox" {
  name = local.policy_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RWObjects"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          # AbortMultipartUpload is necessary so the file-sync sidecar can
          # clean up parts from failed/abandoned uploads. Without it,
          # orphaned parts accumulate silently (billed but invisible to
          # `s3:ListBucket`). Paired with the lifecycle rule below as a
          # backstop.
          "s3:AbortMultipartUpload",
        ]
        Resource = "${aws_s3_bucket.sandbox.arn}/*"
      },
      {
        Sid      = "ListBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.sandbox.arn
      },
    ]
  })

  tags = var.tags
}

resource "aws_iam_role" "sandbox" {
  name = local.role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.oidc_issuer}"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_issuer}:aud" = "sts.amazonaws.com"
            "${local.oidc_issuer}:sub" = local.trust_subjects
          }
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "sandbox" {
  role       = aws_iam_role.sandbox.name
  policy_arn = aws_iam_policy.sandbox.arn
}
