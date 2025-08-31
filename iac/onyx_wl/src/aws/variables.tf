variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "availability_zone_onyx_wl" {
  description = "AZ for Onyx WL Node"
  type        = string
  default     = "us-east-1a"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr_onyx_wl" {
  description = "CIDR block for master subnet"
  type        = string
  default     = "10.0.1.0/24"
}