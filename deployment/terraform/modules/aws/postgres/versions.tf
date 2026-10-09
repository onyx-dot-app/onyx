terraform {
  required_version = ">= 1.12.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Widened like s3: an internal stack has been running this module against
      # aws 6.x, so 6.x support is observed rather than assumed. vpc and eks
      # stay on 5.x -- vpc until its flow log migrates off log_group_name.
      version = ">= 5.100, < 7.0"
    }
  }
}
