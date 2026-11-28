terraform {
  required_version = ">= 1.12.0"

  required_providers {
    google = {
      source = "hashicorp/google"
      # 7.33 added deletion_policy to google_compute_security_policy, which
      # deletion_protection maps onto. Labels on the policy arrived in 7.3.
      version = "~> 7.33"
    }
  }
}
