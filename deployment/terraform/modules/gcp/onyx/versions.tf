terraform {
  required_version = ">= 1.12.0"

  required_providers {
    # The highest floor among the child modules: gcs and cloud-armor need 7.33
    # for deletion_policy.
    google = {
      source  = "hashicorp/google"
      version = "~> 7.33"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.37"
    }
  }
}
