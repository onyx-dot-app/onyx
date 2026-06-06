variable "cluster_name" {
  type        = string
  description = "EKS cluster name (used to name resources)."
}

variable "oidc_provider_arn" {
  type        = string
  description = "EKS OIDC provider ARN (from the eks module output) for the IRSA trust policy."
}

variable "oidc_provider" {
  type        = string
  description = "EKS OIDC issuer host/path without https:// (from the eks module output) for the sub/aud condition keys."
}

variable "bucket_name" {
  type        = string
  description = "S3 bucket name for sandbox snapshots / file-sync."
}

variable "create_bucket" {
  type        = bool
  description = "Whether to create and manage the sandbox S3 bucket. Set false to reuse an existing bucket named by bucket_name."
  default     = true
}

variable "sandbox_namespace" {
  type        = string
  description = "Kubernetes namespace the sandbox file-sync ServiceAccount lives in."
  default     = "onyx-sandboxes"
}

variable "service_account_name" {
  type        = string
  description = "Name of the sandbox file-sync ServiceAccount the IRSA role trusts."
  default     = "sandbox-file-sync"
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to created resources."
  default     = {}
}
