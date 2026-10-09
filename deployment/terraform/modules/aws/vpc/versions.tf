terraform {
  required_version = ">= 1.12.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Pinned to 5.x: aws_flow_log.log_group_name was removed in provider 6.0.
      # Migrate the flow log to log_destination before relaxing this.
      version = "~> 5.100"
    }
  }
}
