variable "vpc_name" {
  type        = string
  description = "The name of the VPC"
  default     = "onyx-vpc"
}

variable "cidr_block" {
  type        = string
  description = "The CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "private_subnets" {
  type        = list(string)
  description = "The private subnets for the VPC"
  default     = ["10.0.0.0/21", "10.0.8.0/21", "10.0.16.0/21", "10.0.24.0/21", "10.0.32.0/21"]
}

variable "public_subnets" {
  type        = list(string)
  description = "The public subnets for the VPC"
  default     = ["10.0.40.0/21", "10.0.48.0/21", "10.0.56.0/21"]
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to all VPC-related resources"
  default     = {}
}

variable "create_s3_vpc_endpoint" {
  type        = bool
  description = "Whether to create a gateway VPC endpoint for S3"
  default     = true
}

variable "single_nat_gateway" {
  type        = bool
  description = "Route all private subnets through one NAT gateway. Cheaper, but the NAT becomes a single-AZ dependency. False provisions one per AZ."
  default     = false
}
