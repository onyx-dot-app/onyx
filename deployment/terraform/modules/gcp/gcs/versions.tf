terraform {
  required_version = ">= 1.12.0"

  required_providers {
    # 7.33 is the first release with `deletion_policy` on google_storage_bucket,
    # which is how deletion_protection is enforced. Earlier 7.x releases reject
    # the argument at plan time.
    google = {
      source  = "hashicorp/google"
      version = "~> 7.33"
    }
  }
}
