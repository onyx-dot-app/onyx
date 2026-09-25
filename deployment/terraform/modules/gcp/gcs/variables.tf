variable "name" {
  type        = string
  description = "Bucket name. Must be globally unique across GCS. Names with dots need Search Console domain verification, so prefer hyphens."

  # GCS also caps dotted names at 222 characters, but a dotted name needs a
  # verified domain, so this keeps to the plain 63-character rule.
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.name))
    error_message = "name must be 3-63 characters of lowercase letters, digits, hyphens, underscores and dots, and must start and end with a letter or digit."
  }

  validation {
    condition     = !startswith(var.name, "goog") && !strcontains(var.name, "google")
    error_message = "name cannot start with \"goog\" or contain \"google\" (GCS reserves them)."
  }

  validation {
    condition     = !can(regex("^[0-9]{1,3}(\\.[0-9]{1,3}){3}$", var.name))
    error_message = "name cannot be an IP address in dotted-decimal form."
  }

  validation {
    condition     = !strcontains(var.name, "..") && !strcontains(var.name, ".-") && !strcontains(var.name, "-.")
    error_message = "name cannot contain \"..\", \".-\" or \"-.\": each dot-separated part must start and end with a letter or digit."
  }
}

variable "project_id" {
  type        = string
  description = "Project that owns the bucket"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project ID: 6-30 characters of lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "location" {
  type        = string
  description = "Bucket location, for example \"US-EAST1\" (region), \"NAM4\" (dual-region) or \"US\" (multi-region). Put it in the GKE region to avoid egress charges. Cannot change after creation."

  validation {
    condition     = can(regex("^[A-Za-z]+[A-Za-z0-9-]*[A-Za-z0-9]$", var.location))
    error_message = "location must be a GCS location such as US-EAST1, NAM4 or US."
  }
}

variable "storage_class" {
  type        = string
  description = "Default storage class for new objects. STANDARD suits a file store that Onyx reads on demand."
  default     = "STANDARD"

  validation {
    condition     = contains(["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"], var.storage_class)
    error_message = "storage_class must be one of: STANDARD, NEARLINE, COLDLINE, ARCHIVE."
  }
}

variable "versioning_enabled" {
  type        = bool
  description = "Keep previous versions of overwritten and deleted objects"
  default     = true
}

variable "noncurrent_version_retention_days" {
  type        = number
  description = "Days to keep a non-current object version before it is deleted. Only applies when versioning_enabled is true."
  default     = 30

  validation {
    condition     = var.noncurrent_version_retention_days >= 1 && floor(var.noncurrent_version_retention_days) == var.noncurrent_version_retention_days
    error_message = "noncurrent_version_retention_days must be a whole number of at least 1."
  }
}

# Nearline bills a 30-day minimum per object, so a short value costs more than
# it saves on files that are deleted soon after upload.
variable "nearline_after_days" {
  type        = number
  description = "Days after creation before an object moves to NEARLINE. Null disables the transition. Below 30 the early-deletion charge outweighs the storage saving."
  default     = null

  validation {
    condition     = var.nearline_after_days == null ? true : (var.nearline_after_days >= 1 && floor(var.nearline_after_days) == var.nearline_after_days)
    error_message = "nearline_after_days must be null (disabled) or a whole number of at least 1."
  }

  # GCS only moves objects to a colder class, and the rule only matches
  # STANDARD objects, so on any other default class it would never fire.
  validation {
    condition     = var.nearline_after_days == null || var.storage_class == "STANDARD"
    error_message = "nearline_after_days only works with storage_class = \"STANDARD\". Objects already in NEARLINE or colder cannot move to NEARLINE."
  }
}

variable "force_destroy" {
  type        = bool
  description = "Delete every object when the bucket is destroyed. Off by default so a destroy fails on a bucket that still holds files."
  default     = false
}

variable "deletion_protection" {
  type        = bool
  description = "Refuse to destroy the bucket from Terraform. Set false and apply before a planned teardown."
  default     = true
}

variable "kms_key_name" {
  type        = string
  description = "Cloud KMS key for default encryption (CMEK). Null uses Google-managed keys. The project's GCS service agent needs roles/cloudkms.cryptoKeyEncrypterDecrypter on the key before apply, and the key must be in the bucket's location."
  default     = null

  validation {
    condition     = var.kms_key_name == null ? true : can(regex("^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$", var.kms_key_name))
    error_message = "kms_key_name must be a full key name: projects/<project>/locations/<location>/keyRings/<ring>/cryptoKeys/<key>."
  }
}

variable "object_admin_members" {
  type        = list(string)
  description = "IAM principals that read and write the file store, for example the Onyx workload identity principal (principal://...). Each gets roles/storage.objectAdmin and roles/storage.legacyBucketReader on this bucket only."
  default     = []

  # The prefix list leaves out allUsers and allAuthenticatedUsers on purpose:
  # public access prevention would reject them at apply time anyway.
  validation {
    condition = alltrue([
      for m in var.object_admin_members :
      can(regex("^(user|serviceAccount|group|domain|principal|principalSet):.+$", m))
    ])
    error_message = "Each object_admin_members entry must be an IAM member string such as serviceAccount:<email> or principal://iam.googleapis.com/... allUsers and allAuthenticatedUsers are refused."
  }
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to the bucket"
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.labels :
      can(regex("^[a-z][a-z0-9_-]{0,62}$", k)) && can(regex("^[a-z0-9_-]{0,63}$", v))
    ])
    error_message = "Label keys must start with a lowercase letter, and keys and values may hold only lowercase letters, digits, hyphens and underscores (63 characters max)."
  }
}
