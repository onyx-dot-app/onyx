output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnets" {
  value = module.vpc.private_subnets
}

output "public_subnets" {
  value = module.vpc.public_subnets
}

output "vpc_cidr_block" {
  value = module.vpc.vpc_cidr_block
}

output "s3_vpc_endpoint_id" {
  description = "ID of the S3 gateway VPC endpoint created for this VPC"
  value       = aws_vpc_endpoint.s3.id
}
