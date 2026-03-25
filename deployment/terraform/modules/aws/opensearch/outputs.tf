output "domain_endpoint" {
  description = "The endpoint of the OpenSearch domain"
  value       = aws_opensearch_domain.main.endpoint
}

output "domain_arn" {
  description = "The ARN of the OpenSearch domain"
  value       = aws_opensearch_domain.main.arn
}

output "domain_id" {
  description = "The unique identifier for the OpenSearch domain"
  value       = aws_opensearch_domain.main.domain_id
}

output "domain_name" {
  description = "The name of the OpenSearch domain"
  value       = aws_opensearch_domain.main.domain_name
}

output "kibana_endpoint" {
  description = "The OpenSearch Dashboards endpoint"
  value       = aws_opensearch_domain.main.dashboard_endpoint
}

output "security_group_id" {
  description = "The ID of the OpenSearch security group"
  value       = length(aws_security_group.opensearch_sg) > 0 ? aws_security_group.opensearch_sg[0].id : null
}
