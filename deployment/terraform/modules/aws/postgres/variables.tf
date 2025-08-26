variable "identifier" {
  type        = string
  description = "Identifier for the database and related resources"
}

variable "db_name" {
  type        = string
  description = "Name of the database"
  default     = "postgres"
}

variable "instance_type" {
  type        = string
  description = "Instance type"
  default     = "db.t4g.large" # 2 vCPU and 8 GB of memory
}

variable "storage_gb" {
  type        = number
  description = "Storage size in GB"
  default     = 20
}

variable "engine_version" {
  type        = string
  description = "Engine version"
  default     = "17"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnet IDs"
}

variable "ingress_cidrs" {
  type        = list(string)
  description = "Ingress CIDR blocks"
}

variable "username" {
  type        = string
  description = "Username for the database"
  default     = "postgres"
  sensitive   = true
}

variable "password" {
  type        = string
  description = "Password for the database"
  default     = null
  sensitive   = true
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to RDS resources"
  default     = {}
}

variable "enable_rds_iam_auth" {
  type        = bool
  description = "Enable AWS IAM database authentication for this RDS instance"
  default     = false
}
