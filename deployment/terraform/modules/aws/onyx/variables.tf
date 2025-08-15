variable "name" {
  type        = string
  description = "Name of the Onyx resources. Example: 'onyx'"
  default     = "onyx"
}

variable "region" {
  type        = string
  description = "AWS region for all resources"
  default     = "us-west-2"
}

variable "create_vpc" {
  type        = bool
  description = "Whether to create a new VPC"
  default     = true
}

variable "vpc_id" {
  type        = string
  description = "ID of the VPC. Required if create_vpc is false."
  default     = null
}

variable "private_subnets" {
  type        = list(string)
  description = "Private subnets. Required if create_vpc is false."
  default     = [] # This will default to 0.0.0.0/0 if not provided
}

variable "public_subnets" {
  type        = list(string)
  description = "Public subnets. Required if create_vpc is false."
  default     = []
}

variable "vpc_cidr_block" {
  type        = string
  description = "VPC CIDR block. Required if create_vpc is false."
  default     = null
}

variable "tags" {
  type        = map(string)
  description = "Base tags applied to all AWS resources"
  default = {
    "project" = "onyx"
  }
}

variable "postgres_username" {
  type        = string
  description = "Username for the postgres database"
  default     = "postgres"
  sensitive   = true
}

variable "postgres_password" {
  type        = string
  description = "Password for the postgres database"
  default     = null
  sensitive   = true
}

variable "public_cluster_enabled" {
  type        = bool
  description = "Whether to enable public cluster access"
  default     = true
}

variable "private_cluster_enabled" {
  type        = bool
  description = "Whether to enable private cluster access"
  default     = false # Should be true for production, false for dev/staging
}

variable "cluster_endpoint_public_access_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to access the public EKS API endpoint"
  default     = []
}

variable "redis_auth_token" {
  type        = string
  description = "Authentication token for the Redis cluster"
  default     = null
  sensitive   = true
}
