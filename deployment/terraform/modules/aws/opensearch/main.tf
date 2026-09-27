# OpenSearch domain security group
resource "aws_security_group" "opensearch_sg" {
  count       = length(var.security_group_ids) > 0 ? 0 : 1
  name        = "${var.name}-sg"
  description = "Allow inbound traffic to OpenSearch from VPC"
  vpc_id      = var.vpc_id
  tags        = var.tags

  ingress {
    from_port   = 443
    to_port     = 443
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

# Service-linked role for OpenSearch (required for VPC deployment)
# This may already exist in your account - if so, import it or set create_service_linked_role = false
resource "aws_iam_service_linked_role" "opensearch" {
  count            = var.create_service_linked_role ? 1 : 0
  aws_service_name = "opensearchservice.amazonaws.com"
}

# IAM policy for OpenSearch access
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# KMS key lookup for encryption at rest
data "aws_kms_key" "opensearch" {
  key_id = "alias/aws/es"
}

# Access policy - allows all principals within the VPC (secured by VPC + security groups)
data "aws_iam_policy_document" "opensearch_access" {
  statement {
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = ["es:*"]

    resources = [
      "arn:aws:es:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:domain/${var.name}/*"
    ]
  }
}

# OpenSearch domain
resource "aws_opensearch_domain" "main" {
  domain_name    = var.name
  engine_version = "OpenSearch_${var.engine_version}"

  cluster_config {
    instance_type                 = var.instance_type
    instance_count                = var.instance_count
    zone_awareness_enabled        = var.zone_awareness_enabled
    dedicated_master_enabled      = var.dedicated_master_enabled
    dedicated_master_type         = var.dedicated_master_enabled ? var.dedicated_master_type : null
    dedicated_master_count        = var.dedicated_master_enabled ? var.dedicated_master_count : null
    multi_az_with_standby_enabled = var.multi_az_with_standby_enabled
    warm_enabled                  = var.warm_enabled
    warm_type                     = var.warm_enabled ? var.warm_type : null
    warm_count                    = var.warm_enabled ? var.warm_count : null

    dynamic "zone_awareness_config" {
      for_each = var.zone_awareness_enabled ? [1] : []
      content {
        availability_zone_count = var.availability_zone_count
      }
    }

    dynamic "cold_storage_options" {
      for_each = var.cold_storage_enabled ? [1] : []
      content {
        enabled = true
      }
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = var.ebs_volume_type
    volume_size = var.ebs_volume_size
    iops        = var.ebs_volume_type == "gp3" || var.ebs_volume_type == "io1" ? var.ebs_iops : null
    throughput  = var.ebs_volume_type == "gp3" ? var.ebs_throughput : null
  }

  vpc_options {
    subnet_ids         = var.subnet_ids
    security_group_ids = length(var.security_group_ids) > 0 ? var.security_group_ids : [aws_security_group.opensearch_sg[0].id]
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_id != null ? var.kms_key_id : data.aws_kms_key.opensearch.arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = var.tls_security_policy
  }

  advanced_security_options {
    enabled                        = true
    anonymous_auth_enabled         = false
    internal_user_database_enabled = var.internal_user_database_enabled

    dynamic "master_user_options" {
      for_each = var.internal_user_database_enabled ? [1] : []
      content {
        master_user_name     = var.master_user_name
        master_user_password = var.master_user_password
      }
    }

    dynamic "master_user_options" {
      for_each = var.internal_user_database_enabled ? [] : [1]
      content {
        master_user_arn = var.master_user_arn
      }
    }
  }

  advanced_options = var.advanced_options

  access_policies = data.aws_iam_policy_document.opensearch_access.json

  auto_tune_options {
    desired_state       = var.auto_tune_enabled ? "ENABLED" : "DISABLED"
    rollback_on_disable = var.auto_tune_rollback_on_disable
  }

  off_peak_window_options {
    enabled = var.off_peak_window_enabled

    dynamic "off_peak_window" {
      for_each = var.off_peak_window_enabled ? [1] : []
      content {
        window_start_time {
          hours   = var.off_peak_window_start_hours
          minutes = var.off_peak_window_start_minutes
        }
      }
    }
  }

  software_update_options {
    auto_software_update_enabled = var.auto_software_update_enabled
  }

  dynamic "log_publishing_options" {
    for_each = var.enable_logging ? ["INDEX_SLOW_LOGS", "SEARCH_SLOW_LOGS", "ES_APPLICATION_LOGS"] : []
    content {
      cloudwatch_log_group_arn = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:${local.log_group_name}"
      log_type                 = log_publishing_options.value
    }
  }

  tags = var.tags

  depends_on = [
    aws_iam_service_linked_role.opensearch,
    aws_cloudwatch_log_resource_policy.opensearch
  ]

  lifecycle {
    # The master password is managed out-of-band (ESO / the app secret). AWS
    # re-validates it on ANY domain update (even a tag change) and always shows it
    # as a diff since it can't be read back — so Terraform re-sending it turns an
    # unrelated tag update into a hard failure whenever the stored value doesn't
    # meet OpenSearch's current complexity rules. Ignore it here; it's set on
    # create and rotated externally thereafter.
    ignore_changes = [
      advanced_security_options[0].master_user_options[0].master_user_password,
    ]
    precondition {
      condition     = !var.internal_user_database_enabled || var.master_user_name != null
      error_message = "master_user_name is required when internal_user_database_enabled is true."
    }
    precondition {
      condition     = !var.internal_user_database_enabled || var.master_user_password != null
      error_message = "master_user_password is required when internal_user_database_enabled is true."
    }
  }
}

# CloudWatch log group for OpenSearch
locals {
  log_group_name = var.log_group_name != null ? var.log_group_name : "/aws/OpenSearchService/domains/${var.name}/search-logs"
}

resource "aws_cloudwatch_log_group" "opensearch" {
  count             = var.enable_logging ? 1 : 0
  name              = local.log_group_name
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# CloudWatch log resource policy for OpenSearch
data "aws_iam_policy_document" "opensearch_log_policy" {
  count = var.enable_logging ? 1 : 0

  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["es.amazonaws.com"]
    }

    actions = [
      "logs:PutLogEvents",
      "logs:CreateLogStream",
    ]

    resources = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:${local.log_group_name}:*"]
  }
}

resource "aws_cloudwatch_log_resource_policy" "opensearch" {
  count           = var.enable_logging ? 1 : 0
  policy_name     = "OpenSearchService-${var.name}-Search-logs"
  policy_document = data.aws_iam_policy_document.opensearch_log_policy[0].json
}

# ----------------------------------------------------------------------------
# CloudWatch alarms (AWS/ES). Route to alarm_actions (SNS -> PagerDuty). These
# cover the managed-domain clusters; clusters that run OpenSearch as an in-cluster
# pod get their disk/pod failure modes from the kube-level PrometheusRules instead.
# ----------------------------------------------------------------------------

locals {
  os_dimensions = {
    DomainName = var.name
    ClientId   = data.aws_caller_identity.current.account_id
  }
}

# Red = one or more primary shards unallocated -> data unavailable. (Yellow is
# structural on single-node domains and is intentionally NOT alarmed.)
resource "aws_cloudwatch_metric_alarm" "cluster_status_red" {
  alarm_name          = "${var.name}-cluster-status-red"
  alarm_description   = "OpenSearch ${var.name} cluster status RED — data unavailable"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ClusterStatus.red"
  namespace           = "AWS/ES"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  dimensions    = local.os_dimensions
  tags          = var.tags
}

# Writes blocked = the flood-stage / disk-full state that surfaces as
# "IndexWriter is closed" and stalls indexing. Highest-value OpenSearch alarm.
resource "aws_cloudwatch_metric_alarm" "cluster_index_writes_blocked" {
  alarm_name          = "${var.name}-index-writes-blocked"
  alarm_description   = "OpenSearch ${var.name} is blocking index writes (flood-stage / disk)"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ClusterIndexWritesBlocked"
  namespace           = "AWS/ES"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  dimensions    = local.os_dimensions
  tags          = var.tags
}

# FreeStorageSpace is reported in MB (per node); Minimum catches the fullest node,
# which is what trips the flood-stage write block above.
resource "aws_cloudwatch_metric_alarm" "free_storage" {
  alarm_name          = "${var.name}-free-storage"
  alarm_description   = "OpenSearch ${var.name} free storage low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/ES"
  period              = 300
  statistic           = "Minimum"
  threshold           = var.free_storage_threshold_mb != null ? var.free_storage_threshold_mb : var.ebs_volume_size * 1024 * 0.15
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  dimensions    = local.os_dimensions
  tags          = var.tags
}

# Sustained JVM heap pressure -> GC thrash / node instability.
resource "aws_cloudwatch_metric_alarm" "jvm_memory_pressure" {
  alarm_name          = "${var.name}-jvm-memory-pressure"
  alarm_description   = "OpenSearch ${var.name} JVM memory pressure high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "JVMMemoryPressure"
  namespace           = "AWS/ES"
  period              = 300
  statistic           = "Maximum"
  threshold           = var.jvm_memory_pressure_threshold_percent
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  dimensions    = local.os_dimensions
  tags          = var.tags
}

# Fewer reachable nodes than provisioned = a node dropped out of the cluster.
resource "aws_cloudwatch_metric_alarm" "nodes" {
  alarm_name          = "${var.name}-nodes-low"
  alarm_description   = "OpenSearch ${var.name} has fewer nodes than expected"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "Nodes"
  namespace           = "AWS/ES"
  period              = 300
  statistic           = "Minimum"
  threshold           = var.instance_count
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  dimensions    = local.os_dimensions
  tags          = var.tags
}
