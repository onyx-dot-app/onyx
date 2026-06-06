# Craft sandbox cloud prereqs: encrypted S3 snapshot bucket + IRSA role for the
# sandbox file-sync SA. Outputs role_arn + bucket_name for Helm.

locals {
  # OIDC passed as inputs (not a data source) so this works in the same apply that
  # creates the cluster, and on destroy after it's gone.
  oidc_url                = var.oidc_provider
  oidc_arn                = var.oidc_provider_arn
  sa_sub                  = "system:serviceaccount:${var.sandbox_namespace}:${var.service_account_name}"
  bucket_arn              = "arn:aws:s3:::${var.bucket_name}"
  cluster_name_iam_suffix = length(var.cluster_name) <= 44 ? var.cluster_name : "${substr(var.cluster_name, 0, 35)}-${substr(sha1(var.cluster_name), 0, 8)}"
}

resource "aws_s3_bucket" "sandbox" {
  count  = var.create_bucket ? 1 : 0
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sandbox" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.sandbox[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "sandbox" {
  count                   = var.create_bucket ? 1 : 0
  bucket                  = aws_s3_bucket.sandbox[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "sandbox" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.sandbox[0].id
  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {} # applies to all objects (required by the provider)
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_iam_policy" "sandbox_s3" {
  name        = "${var.cluster_name}-sandbox-s3-policy"
  description = "Sandbox file-sync S3 access for ${var.cluster_name}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
        Resource = "${local.bucket_arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = local.bucket_arn
      }
    ]
  })
}

resource "aws_iam_role" "sandbox_file_sync" {
  name = "SandboxFileSyncRole-${local.cluster_name_iam_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = local.oidc_arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_url}:sub" = local.sa_sub
            "${local.oidc_url}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "sandbox_s3" {
  role       = aws_iam_role.sandbox_file_sync.name
  policy_arn = aws_iam_policy.sandbox_s3.arn
}
