terraform {
  required_version = ">= 1.12.0"

  required_providers {
    # 7.8 is the first release with `deletion_protection` on
    # google_redis_instance, which this module sets from a variable.
    google = {
      source  = "hashicorp/google"
      version = "~> 7.8"
    }
  }
}
