variable "bucket_name" {
  type        = string
  description = "Name of the S3 bucket"
}

variable "region" {
  type        = string
  description = "AWS region"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID where your EKS cluster runs"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to S3 resources and VPC endpoint"
  default     = {}
}
