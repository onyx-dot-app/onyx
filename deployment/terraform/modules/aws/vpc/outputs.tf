output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnets" {
  value = module.vpc.private_subnets
}

output "public_subnets" {
  value = module.vpc.public_subnets
}

output "nat_gateway_public_ips" {
  description = "Public Elastic IPs assigned to the VPC NAT gateways"
  value       = module.vpc.nat_public_ips
}

output "vpc_cidr_block" {
  value = module.vpc.vpc_cidr_block
}

output "s3_vpc_endpoint_id" {
  description = "ID of the S3 gateway VPC endpoint created for this VPC"
  value       = try(aws_vpc_endpoint.s3[0].id, null)
}
