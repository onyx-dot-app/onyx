# Define the Redis security group
resource "aws_security_group" "redis_sg" {
  name        = "${var.name}-sg"
  description = "Allow inbound traffic from EKS to Redis"
  vpc_id      = var.vpc_id
  tags        = var.tags

  # Standard Redis port
  ingress {
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_elasticache_subnet_group" "elasticache_subnet_group" {
  name       = "${var.name}-subnet-group"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

# The actual Redis instance
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = var.name
  description          = "Redis cluster for ${var.name}"
  engine               = "redis"
  node_type            = var.instance_type
  num_cache_clusters   = 1
  parameter_group_name = "default.redis7"
  engine_version       = "7.0"
  port                 = 6379
  security_group_ids   = [aws_security_group.redis_sg.id]
  subnet_group_name    = aws_elasticache_subnet_group.elasticache_subnet_group.name

  # Enable transit encryption (SSL/TLS)
  transit_encryption_enabled = var.transit_encryption_enabled

  # Enable encryption at rest
  at_rest_encryption_enabled = true

  # Enable authentication if auth_token is provided
  # If transit_encryption_enabled is true, AWS requires an auth_token to be set.
  auth_token = var.auth_token
  tags       = var.tags
}
