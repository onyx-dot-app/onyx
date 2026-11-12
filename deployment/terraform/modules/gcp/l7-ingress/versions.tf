terraform {
  required_version = ">= 1.12.0"

  required_providers {
    # 7.33 added deletion_policy to the address and the DNS authorization,
    # which deletion_protection maps onto.
    google = {
      source  = "hashicorp/google"
      version = "~> 7.33"
    }
  }
}
