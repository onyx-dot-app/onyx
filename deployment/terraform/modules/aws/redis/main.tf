# The module now skips creating its own security group when the caller passes
# security_group_ids, so the SG moved from a bare address to index 0. No-op for
# state that is already indexed.
moved {
  from = aws_security_group.redis_sg
  to   = aws_security_group.redis_sg[0]
}

# Define the Redis security group (skipped when security_group_ids is provided)
resource "aws_security_group" "redis_sg" {
  count       = length(var.security_group_ids) == 0 ? 1 : 0
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
  security_group_ids   = length(var.security_group_ids) > 0 ? var.security_group_ids : [aws_security_group.redis_sg[0].id]
  subnet_group_name    = aws_elasticache_subnet_group.elasticache_subnet_group.name

  # Enable transit encryption (SSL/TLS)
  transit_encryption_enabled = var.transit_encryption_enabled

  # Enable encryption at rest
  at_rest_encryption_enabled = true

  # Enable authentication if auth_token is provided
  # If transit_encryption_enabled is true, AWS requires an auth_token to be set.
  # For IAM authentication, auth_token can be null
  auth_token = var.enable_redis_iam_auth ? null : var.auth_token
  tags       = var.tags
}

# The single member node's cluster id (num_cache_clusters = 1). ElastiCache
# publishes per-node CloudWatch metrics under the CacheClusterId dimension.
locals {
  cache_cluster_id = tolist(aws_elasticache_replication_group.redis.member_clusters)[0]
}

# Memory is the failure mode that has actually taken clusters down: a broker
# whose keys never expire climbs to maxmemory, evictions can't free anything, and
# Redis starts rejecting writes -> the whole celery fleet crashloops at once.
# DatabaseMemoryUsagePercentage is the leading indicator.
resource "aws_cloudwatch_metric_alarm" "memory_high" {
  alarm_name          = "${var.name}-memory-high"
  alarm_description   = "ElastiCache ${var.name} memory usage high (warning)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "DatabaseMemoryUsagePercentage"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = var.memory_high_threshold_percent
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = { CacheClusterId = local.cache_cluster_id }
  tags       = var.tags
}

resource "aws_cloudwatch_metric_alarm" "memory_critical" {
  alarm_name          = "${var.name}-memory-critical"
  alarm_description   = "ElastiCache ${var.name} memory usage critical — writes may be rejected, celery fleet at risk"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseMemoryUsagePercentage"
  namespace           = "AWS/ElastiCache"
  period              = 60
  statistic           = "Average"
  threshold           = var.memory_critical_threshold_percent
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = { CacheClusterId = local.cache_cluster_id }
  tags       = var.tags
}

# Redis is single-threaded, so EngineCPUUtilization (the Redis engine thread) is
# the meaningful CPU signal, not host CPUUtilization.
resource "aws_cloudwatch_metric_alarm" "engine_cpu_high" {
  alarm_name          = "${var.name}-engine-cpu-high"
  alarm_description   = "ElastiCache ${var.name} Redis engine CPU high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "EngineCPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = var.engine_cpu_threshold_percent
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = { CacheClusterId = local.cache_cluster_id }
  tags       = var.tags
}

# Swap on an in-memory store means it has overrun physical memory — always a
# problem, precedes the memory-critical failure.
resource "aws_cloudwatch_metric_alarm" "swap_usage" {
  alarm_name          = "${var.name}-swap-usage"
  alarm_description   = "ElastiCache ${var.name} is swapping — memory pressure"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "SwapUsage"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = var.swap_usage_threshold_bytes
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = { CacheClusterId = local.cache_cluster_id }
  tags       = var.tags
}
