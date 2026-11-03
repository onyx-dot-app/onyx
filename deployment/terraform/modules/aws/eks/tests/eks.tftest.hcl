# Plans the module against mocked providers, so these run without an AWS
# account or a cluster. Run with `terraform test` from the module directory.

mock_provider "aws" {
  # The provider still validates ARNs and policy JSON, so random mock strings fail.
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:role/terraform"
    }
  }
  mock_data "aws_iam_session_context" {
    defaults = {
      issuer_arn = "arn:aws:iam::123456789012:role/terraform"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
  mock_data "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
    }
  }
  mock_data "aws_partition" {
    defaults = {
      partition  = "aws"
      dns_suffix = "amazonaws.com"
    }
  }
  mock_data "aws_region" {
    defaults = {
      region = "us-east-2"
      name   = "us-east-2"
    }
  }
}

mock_provider "helm" {}
mock_provider "kubernetes" {}
mock_provider "tls" {}
mock_provider "time" {}
mock_provider "cloudinit" {}
mock_provider "null" {}

variables {
  cluster_name = "onyx"
  vpc_id       = "vpc-0123456789abcdef0"
  subnet_ids   = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
}

run "defaults_plan" {
  command = plan

  assert {
    condition     = local.node_group_defaults.metadata_options.http_put_response_hop_limit == 2
    error_message = "Node groups must keep the v20 IMDS hop limit of 2, or the upgrade rolls every node."
  }

  assert {
    condition     = local.node_group_defaults.enable_monitoring && !local.node_group_defaults.use_latest_ami_release_version
    error_message = "Node groups must keep v20 detailed monitoring and must not move to the latest AMI release."
  }

  assert {
    condition     = !local.node_group_defaults.enable_efa_only
    error_message = "Node groups must keep the v20 enable_efa_only default of false."
  }
}

run "optional_node_groups_and_addons_plan" {
  command = plan

  variables {
    enable_gpu_node       = true
    enable_craft          = true
    enable_network_policy = true
  }

  assert {
    condition     = local.craft_sandbox_node_groups.sandbox.metadata_options.http_put_response_hop_limit == 1
    error_message = "The sandbox node group must keep IMDS hop limit 1 so sandboxed pods cannot reach node credentials."
  }
}
