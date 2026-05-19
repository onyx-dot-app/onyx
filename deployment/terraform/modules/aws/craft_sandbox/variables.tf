variable "cluster_name" {
  description = "EKS cluster name. Used for default resource naming."
  type        = string
}

variable "cluster_oidc_issuer_url" {
  description = "EKS cluster OIDC issuer URL (https://oidc.eks.<region>.amazonaws.com/id/<id>). The `https://` prefix is optional; the module strips it before use."
  type        = string
}

variable "bucket_name" {
  description = "Globally-unique S3 bucket name for sandbox snapshots / file-sync."
  type        = string
}

variable "sandbox_namespace" {
  description = "Kubernetes namespace where the sandbox-file-sync ServiceAccount lives. Must match `configMap.SANDBOX_NAMESPACE` in the Helm values."
  type        = string
  default     = "onyx-sandboxes"
}

variable "service_account_name" {
  description = "Kubernetes ServiceAccount name bound to this IAM role via IRSA. Must match `configMap.SANDBOX_SERVICE_ACCOUNT_NAME` in the Helm values."
  type        = string
  default     = "sandbox-file-sync"
}

variable "extra_trust_subjects" {
  description = "Additional `sub` claims (beyond the primary `system:serviceaccount:<sandbox_namespace>:<service_account_name>`) that may assume this role. Rarely needed; useful when migrating from an older configuration that bound a different SA to this role."
  type        = list(string)
  default     = []
}

variable "role_name" {
  description = "Override for the IAM role name. Defaults to `SandboxFileSyncRole-<cluster_name>`."
  type        = string
  default     = null
}

variable "policy_name" {
  description = "Override for the IAM policy name. Defaults to `<cluster_name>-sandbox-s3-policy`."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags to apply to provisioned AWS resources."
  type        = map(string)
  default     = {}
}
