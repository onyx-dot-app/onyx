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

  assert {
    condition = (
      !contains(keys(local.craft_sandbox_node_groups.sandbox.labels), "onyx.app/kvm") &&
      !contains(keys(local.craft_sandbox_node_groups.sandbox), "cpu_options") &&
      !contains(keys(local.craft_sandbox_node_groups.sandbox), "capacity_type")
    )
    error_message = "The default pod runtime must leave the sandbox node group unchanged: no kvm label, cpu_options or capacity_type."
  }

  assert {
    condition = (
      local.craft_sandbox_node_groups.sandbox.block_device_mappings.xvda.ebs.iops == 3000 &&
      local.craft_sandbox_node_groups.sandbox.block_device_mappings.xvda.ebs.throughput == 125
    )
    error_message = "Default sandbox disk IOPS and throughput must stay at 3000 and 125."
  }
}

run "firecracker_nested_plan" {
  command = plan

  variables {
    enable_craft                       = true
    craft_sandbox_runtime              = "firecracker"
    craft_sandbox_node_instance_types  = ["m8i.2xlarge", "c8i-flex.4xlarge"]
    craft_sandbox_node_disk_iops       = 6000
    craft_sandbox_node_disk_throughput = 500
  }

  assert {
    condition     = local.craft_sandbox_node_groups.sandbox.cpu_options.nested_virtualization == "enabled"
    error_message = "Firecracker on non-metal types must turn on nested virtualization."
  }

  assert {
    condition = (
      local.craft_sandbox_node_groups.sandbox.labels["onyx.app/kvm"] == "true" &&
      local.craft_sandbox_node_groups.sandbox.labels["onyx.app/workload"] == "sandbox"
    )
    error_message = "Firecracker sandbox nodes must keep the workload label and add onyx.app/kvm=true."
  }

  assert {
    condition     = local.craft_sandbox_node_groups.sandbox.capacity_type == "ON_DEMAND"
    error_message = "Firecracker sandbox nodes must be on-demand, never spot."
  }

  assert {
    condition     = local.craft_sandbox_node_groups.sandbox.metadata_options.http_put_response_hop_limit == 1
    error_message = "Firecracker sandbox nodes must keep IMDS hop limit 1."
  }

  assert {
    condition = (
      local.craft_sandbox_node_groups.sandbox.block_device_mappings.xvda.ebs.iops == 6000 &&
      local.craft_sandbox_node_groups.sandbox.block_device_mappings.xvda.ebs.throughput == 500
    )
    error_message = "Sandbox disk IOPS and throughput must follow the variables."
  }
}

run "firecracker_metal_plan" {
  command = plan

  variables {
    enable_craft                      = true
    craft_sandbox_runtime             = "firecracker"
    craft_sandbox_node_instance_types = ["m7i.metal-24xl", "c6i.metal"]
  }

  assert {
    condition     = !contains(keys(local.craft_sandbox_node_groups.sandbox), "cpu_options")
    error_message = "Metal types expose /dev/kvm directly and must not set nested virtualization."
  }

  assert {
    condition     = local.craft_sandbox_node_groups.sandbox.labels["onyx.app/kvm"] == "true"
    error_message = "Metal Firecracker sandbox nodes must have the onyx.app/kvm=true label."
  }
}

run "firecracker_rejects_m7i_nested" {
  command = plan
  variables {
    enable_craft                      = true
    craft_sandbox_runtime             = "firecracker"
    craft_sandbox_node_instance_types = ["m7i.2xlarge"]
  }
  expect_failures = [var.craft_sandbox_runtime]
}

run "firecracker_rejects_graviton" {
  command = plan
  variables {
    enable_craft                      = true
    craft_sandbox_runtime             = "firecracker"
    craft_sandbox_node_instance_types = ["m8g.2xlarge"]
  }
  expect_failures = [var.craft_sandbox_runtime]
}

run "firecracker_rejects_amd" {
  command = plan
  variables {
    enable_craft                      = true
    craft_sandbox_runtime             = "firecracker"
    craft_sandbox_node_instance_types = ["m8a.2xlarge"]
  }
  expect_failures = [var.craft_sandbox_runtime]
}

run "firecracker_rejects_amd_and_graviton_metal" {
  command = plan
  variables {
    enable_craft                      = true
    craft_sandbox_runtime             = "firecracker"
    craft_sandbox_node_instance_types = ["m7a.metal-48xl", "c7g.metal", "a1.metal"]
  }
  expect_failures = [var.craft_sandbox_runtime]
}

run "firecracker_rejects_mixed_metal_and_nested" {
  command = plan
  variables {
    enable_craft                      = true
    craft_sandbox_runtime             = "firecracker"
    craft_sandbox_node_instance_types = ["m8i.2xlarge", "m7i.metal-24xl"]
  }
  expect_failures = [var.craft_sandbox_runtime]
}

run "pod_runtime_accepts_any_type" {
  command = plan
  variables {
    enable_craft                      = true
    craft_sandbox_node_instance_types = ["m7a.2xlarge"]
  }
}

run "rejects_unknown_runtime" {
  command = plan
  variables {
    craft_sandbox_runtime = "kata"
  }
  expect_failures = [var.craft_sandbox_runtime]
}

run "rejects_throughput_above_gp3_ratio" {
  command = plan
  variables {
    craft_sandbox_node_disk_iops       = 3000
    craft_sandbox_node_disk_throughput = 1000
  }
  expect_failures = [var.craft_sandbox_node_disk_throughput]
}
