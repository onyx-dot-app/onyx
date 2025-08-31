output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.onyx_wl_vpc.id
}

output "subnet_ids" {
  description = "IDs of the created subnets"
  value = [
    aws_subnet.onyx_wl_subnet.id
  ]
}

output "ec2_instance_id" {
  description = "The ID of the provisioned Onyx WL EC2 Instance"
  value       = aws_instance.onyx_wl_node.id
}

output "public_ip_address" {
  description = "Public IP Address of the launched Onyx WL EC2 instance"
  value       = aws_instance.onyx_wl_node.public_ip
}

output "elastic_ip_address" {
  description = "The public IP address of the associated Elastic IP"
  value       = aws_eip.onyx_wl_eip.public_ip
}

output "elastic_ip_domain_name" {
  description = "The domain name associated with the Elastic IP address."
  value       = aws_eip.onyx_wl_eip.public_dns
}