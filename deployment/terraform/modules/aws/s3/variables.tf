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
  # Guarded below: anonymous reads cannot use SigV4, so allow_anonymous_read
  # forces AES256 and a KMS key would be silently dropped.
  description = "Optional KMS key for bucket encryption. Defaults to AWS-managed S3 key."
  type        = string
  default     = null

  validation {
    condition     = var.kms_key_id == "" || var.kms_key_id == null || !var.allow_anonymous_read
    error_message = "kms_key_id cannot be combined with allow_anonymous_read: anonymous requests cannot sign with SigV4, so the bucket is forced to AES256."
  }
}

variable "expiration_days" {
  description = "Number of days after which current objects are expired. Set to 0 to disable."
  type        = number
  default     = 0

  validation {
    condition     = var.expiration_days >= 0
    error_message = "expiration_days must be 0 (disabled) or a positive number of days."
  }
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

variable "additional_policy_documents" {
  # Merged via source_policy_documents, so the module's own statements win on a
  # SID collision. Callers can add statements but cannot replace
  # DenyInsecureTransport.
  description = "IAM policy documents (JSON strings) merged into the bucket policy. Use this to keep custom statements that the module does not generate. Give each statement a SID that no other statement uses."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for doc in var.additional_policy_documents : can(jsondecode(doc))])
    error_message = "Each entry in additional_policy_documents must be a valid JSON policy document."
  }
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
