output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.onyx_wl_vpc.id
}

output "subnet_ids" {
  description = "IDs of the created subnets"
  value = [
    aws_subnet.onyx_wl_subnet.id,
  ]
}

output "public_ip_address" {
  description = "Public IP Address of the launched Onyx WL EC2 instance"
  value       = aws_instance.onyx_wl_node.public_ip
}
