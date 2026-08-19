# These two gained `count`, which renames them `this` -> `this[0]` in state.
# Without these blocks Terraform plans a destroy/create of the subnet group and
# security group of every database already using this module — and the security
# group is attached to a live instance.
moved {
  from = aws_db_subnet_group.this
  to   = aws_db_subnet_group.this[0]
}

moved {
  from = aws_security_group.this
  to   = aws_security_group.this[0]
}

# Skipped when the caller supplies existing networking. Joining the subnet group
# and security groups an existing database already uses is the reliable way to
# inherit its reachability rather than re-deriving it.
resource "aws_db_subnet_group" "this" {
  count      = var.db_subnet_group_name == null ? 1 : 0
  name       = "${var.identifier}-subnet-group"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "this" {
  count       = var.vpc_security_group_ids == null ? 1 : 0
  name        = "${var.identifier}-sg"
  description = "Allow PostgreSQL access"
  vpc_id      = var.vpc_id
  tags        = var.tags

  ingress {
    description = "Postgres ingress"
    from_port   = 5432
    to_port     = 5432
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

resource "aws_db_instance" "this" {
  identifier            = var.identifier
  db_name               = var.db_name
  engine                = "postgres"
  engine_version        = var.engine_version
  instance_class        = var.instance_type
  allocated_storage     = var.storage_gb
  max_allocated_storage = var.max_storage_gb
  storage_type          = var.storage_type
  iops                  = var.iops
  storage_throughput    = var.storage_throughput
  username              = var.username

  # Mutually exclusive: the provider rejects both being set.
  password                    = var.manage_master_user_password ? null : var.password
  manage_master_user_password = var.manage_master_user_password ? true : null

  multi_az                     = var.multi_az
  parameter_group_name         = var.parameter_group_name
  performance_insights_enabled = var.performance_insights_enabled
  maintenance_window           = var.maintenance_window

  # Enable IAM authentication for the RDS instance
  iam_database_authentication_enabled = var.enable_rds_iam_auth

  db_subnet_group_name   = var.db_subnet_group_name != null ? var.db_subnet_group_name : aws_db_subnet_group.this[0].name
  vpc_security_group_ids = var.vpc_security_group_ids != null ? var.vpc_security_group_ids : [aws_security_group.this[0].id]
  publicly_accessible    = false
  deletion_protection    = true
  storage_encrypted      = true

  # Automated backups
  backup_retention_period = var.backup_retention_period
  backup_window           = var.backup_window

  tags = var.tags

  # Guardrail: this instance holds production data. Never let Terraform
  # destroy/replace it — a plan that would (e.g. enabling storage_encrypted on an
  # existing unencrypted instance, which RDS can't do in place) fails here instead
  # of silently recreating an empty DB. A real migration (snapshot -> restore into
  # a new encrypted instance) is done deliberately with this guard removed.
  lifecycle {
    prevent_destroy = true
  }
}

# CloudWatch alarm for CPU utilization monitoring
resource "aws_cloudwatch_metric_alarm" "cpu_utilization" {
  alarm_name          = "${var.identifier}-cpu-utilization"
  alarm_description   = "RDS CPU utilization for ${var.identifier}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.cpu_alarm_evaluation_periods
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = var.cpu_alarm_period
  statistic           = "Average"
  threshold           = var.cpu_alarm_threshold
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.this.identifier
  }

  tags = var.tags
}

# CloudWatch alarm for disk IO monitoring
resource "aws_cloudwatch_metric_alarm" "read_iops" {
  alarm_name          = "${var.identifier}-read-iops"
  alarm_description   = "RDS ReadIOPS for ${var.identifier}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.iops_alarm_evaluation_periods
  metric_name         = "ReadIOPS"
  namespace           = "AWS/RDS"
  period              = var.iops_alarm_period
  statistic           = "Average"
  threshold           = var.read_iops_alarm_threshold
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.this.identifier
  }

  tags = var.tags
}

# FreeStorageSpace floor. A full data volume (WAL runaway, unpurged logs, an
# inactive replication slot) wedges the writer. Default trips at 15% of the base
# allocated storage.
resource "aws_cloudwatch_metric_alarm" "free_storage" {
  alarm_name          = "${var.identifier}-free-storage"
  alarm_description   = "RDS free storage low for ${var.identifier}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.free_storage_threshold_bytes != null ? var.free_storage_threshold_bytes : var.storage_gb * 1024 * 1024 * 1024 * 0.15
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.this.identifier
  }

  tags = var.tags
}

# Connection count near the ceiling. A task holding a session across an external
# call, or a request-cancel leak, saturates the pool and new pods fail startup.
resource "aws_cloudwatch_metric_alarm" "database_connections" {
  alarm_name          = "${var.identifier}-database-connections"
  alarm_description   = "RDS connection count high for ${var.identifier}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.connections_alarm_threshold
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.this.identifier
  }

  tags = var.tags
}

# CloudWatch alarm for freeable memory monitoring
resource "aws_cloudwatch_metric_alarm" "freeable_memory" {
  alarm_name          = "${var.identifier}-freeable-memory"
  alarm_description   = "RDS freeable memory for ${var.identifier}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = var.memory_alarm_evaluation_periods
  metric_name         = "FreeableMemory"
  namespace           = "AWS/RDS"
  period              = var.memory_alarm_period
  statistic           = "Average"
  threshold           = var.memory_alarm_threshold
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.this.identifier
  }

  tags = var.tags
}
