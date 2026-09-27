terraform {
  required_version = ">= 1.12.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Widened so callers already on aws 6.x can consume this module. Only s3
      # is widened: it has no provider-side conditional validation, and it is
      # the module 6.x callers actually need. The others stay on 5.x until
      # something needs them there and can be tested against a real plan.
      version = ">= 5.100, < 7.0"
    }
  }
}
