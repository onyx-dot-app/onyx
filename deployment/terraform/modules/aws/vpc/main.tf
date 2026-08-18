# The S3 gateway endpoint and its route-table lookup became conditional on
# create_s3_vpc_endpoint, so the endpoint moved from a bare address to index 0.
# No-op for state that is already indexed.
moved {
  from = aws_vpc_endpoint.s3
  to   = aws_vpc_endpoint.s3[0]
}

# Get the availability zones for the region without requiring opt-in
data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

data "aws_region" "current" {}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0.0"

  name = var.vpc_name

  cidr = var.cidr_block
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)

  private_subnets         = var.private_subnets
  public_subnets          = var.public_subnets
  map_public_ip_on_launch = true

  enable_nat_gateway   = true
  single_nat_gateway   = var.single_nat_gateway
  enable_dns_hostnames = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }

  tags = var.tags
}

data "aws_route_tables" "this" {
  count = var.create_s3_vpc_endpoint ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [module.vpc.vpc_id]
  }
  depends_on = [module.vpc]
}

resource "aws_vpc_endpoint" "s3" {
  count             = var.create_s3_vpc_endpoint ? 1 : 0
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.this[0].ids
  tags              = var.tags
}

# Create minimal IAM role for VPC Flow Logs (required by AWS)
resource "aws_iam_role" "vpc_flow_logs" {
  name = "${var.vpc_name}-flow-logs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "vpc-flow-logs.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# Attach minimal policy for CloudWatch Logs
resource "aws_iam_role_policy" "vpc_flow_logs" {
  name = "${var.vpc_name}-flow-logs-policy"
  role = aws_iam_role.vpc_flow_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Resource = "*"
      }
    ]
  })
}

# Create VPC Flow Log directly (simpler than module's built-in)
resource "aws_flow_log" "vpc_flow_log" {
  iam_role_arn         = aws_iam_role.vpc_flow_logs.arn
  log_destination_type = "cloud-watch-logs"
  log_group_name       = "/aws/vpc/flow-logs/${var.vpc_name}"
  traffic_type         = "ALL"
  vpc_id               = module.vpc.vpc_id

  tags = merge(var.tags, {
    Name = "${var.vpc_name}-flow-logs"
  })

  # Without this the flow log can be created before the role can write to
  # CloudWatch, and delivery silently fails until the next apply.
  depends_on = [aws_iam_role_policy.vpc_flow_logs]
}
