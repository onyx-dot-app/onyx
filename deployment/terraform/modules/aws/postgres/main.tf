resource "aws_db_subnet_group" "this" {
  name       = "${var.identifier}-subnet-group"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "this" {
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
  identifier        = var.identifier
  db_name           = var.db_name
  engine            = "postgres"
  engine_version    = var.engine_version
  instance_class    = var.instance_type
  allocated_storage = var.storage_gb
  username          = var.username
  password          = var.password

  # Enable IAM authentication for the RDS instance
  iam_database_authentication_enabled = var.enable_rds_iam_auth

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  publicly_accessible    = false
  deletion_protection    = true
  storage_encrypted      = true

  # Automated backups
  backup_retention_period = var.backup_retention_period
  backup_window           = var.backup_window

  tags = var.tags
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
