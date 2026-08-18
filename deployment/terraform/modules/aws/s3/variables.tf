variable "bucket_name" {
  description = "Name of the S3 bucket"
  type        = string
}

variable "force_destroy" {
  description = "Allow bucket deletion even if it contains objects"
  type        = bool
  default     = false
}

variable "enable_versioning" {
  description = "Enable S3 bucket versioning"
  type        = bool
  default     = true
}

variable "kms_key_id" {
  description = "Optional KMS key for bucket encryption. Defaults to AWS-managed S3 key."
  type        = string
  default     = null
}

variable "expiration_days" {
  description = "Number of days after which current objects are expired. Set to 0 to disable."
  type        = number
  default     = 0
}

variable "noncurrent_expiration_days" {
  description = "Number of days to retain noncurrent object versions"
  type        = number
  default     = 90
}

variable "transition_to_ia" {
  description = "Whether to transition objects to Intelligent-Tiering"
  type        = bool
  default     = true
}

variable "transition_to_ia_days" {
  description = "Days after which to transition objects to Intelligent-Tiering"
  type        = number
  default     = 7
}

variable "tags" {
  description = "Additional tags to assign to the bucket"
  type        = map(string)
  default     = {}
}

variable "allowed_vpc_ids" {
  description = "VPC IDs allowed anonymous read. Only used when allow_anonymous_read is true; leaving both this and allowed_source_ips empty grants nothing rather than granting everything."
  type        = list(string)
  default     = []
}

variable "allowed_source_ips" {
  description = "CIDR blocks allowed anonymous read. Only used when allow_anonymous_read is true; leaving both this and allowed_vpc_ids empty grants nothing rather than granting everything."
  type        = list(string)
  default     = []
}

variable "allow_anonymous_read" {
  description = "If true, allow anonymous (unauthenticated) reads from the allowed networks."
  type        = bool
  default     = false
}

variable "s3_vpc_endpoint_id" {
  description = "ID of an S3 gateway VPC endpoint allowed to access this bucket. Leave empty to skip the VPCE policy statement."
  type        = string
  default     = ""
}

# When non-null these override the value the public_access_block resource
# would otherwise inherit from allow_anonymous_read. Lets a caller keep
# anonymous-read wiring (policy + AES256) while still locking the bucket's
# block-public-policy / restrict-public-buckets bits down at the account
# level.
variable "block_public_policy" {
  description = "Override for aws_s3_bucket_public_access_block.block_public_policy. Null = derive from allow_anonymous_read."
  type        = bool
  default     = null
}

variable "restrict_public_buckets" {
  description = "Override for aws_s3_bucket_public_access_block.restrict_public_buckets. Null = derive from allow_anonymous_read."
  type        = bool
  default     = null
}
