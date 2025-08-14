resource "aws_s3_bucket" "bucket" {
  bucket = var.bucket_name
  tags   = var.tags
}

data "aws_route_tables" "vpc" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.vpc.ids
  tags              = var.tags
}

resource "aws_s3_bucket_policy" "bucket_policy" {
  bucket = aws_s3_bucket.bucket.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid       = "AllowAccessViaVPCE",
        Effect    = "Allow",
        Principal = "*", # Update this to be the specific IAM roles, users, or service principals as needed
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
          aws_s3_bucket.bucket.arn,
          "${aws_s3_bucket.bucket.arn}/*"
        ],
        Condition = {
          StringEquals = {
            "aws:SourceVpce" = aws_vpc_endpoint.s3.id
          }
        }
      }
    ]
  })
}
