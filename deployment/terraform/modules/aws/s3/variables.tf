variable "bucket_name" {
  type        = string
  description = "Name of the S3 bucket"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to S3 resources"
  default     = {}
}

variable "s3_vpc_endpoint_id" {
  type        = string
  description = "ID of the S3 gateway VPC endpoint allowed to access this bucket"
}
