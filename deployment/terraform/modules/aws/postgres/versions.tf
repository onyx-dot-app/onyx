terraform {
  required_version = ">= 1.12.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Widened like s3 so callers still on aws 5.x can consume this module.
      version = ">= 5.100, < 7.0"
    }
  }
}
