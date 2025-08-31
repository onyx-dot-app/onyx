terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  required_version = "1.10.5"
}

provider "aws" {
  region = var.region
}

resource "aws_vpc" "onyx_wl_vpc" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "onyx-wl-vpc"
  }
}

resource "aws_internet_gateway" "onyx_wl_igw" {
  vpc_id = aws_vpc.onyx_wl_vpc.id

  tags = {
    Name = "onyx-wl-igw"
  }
}

resource "aws_subnet" "onyx_wl_subnet" {
  vpc_id            = aws_vpc.onyx_wl_vpc.id
  cidr_block        = var.subnet_cidr_onyx_wl
  availability_zone = var.availability_zone_onyx_wl

  map_public_ip_on_launch = true
  depends_on              = [aws_internet_gateway.onyx_wl_igw]

  tags = {
    "Name" = "Onyx WL Public Subnet"
  }
}

resource "aws_route_table" "onyx_wl_rt" {
  vpc_id = aws_vpc.onyx_wl_vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.onyx_wl_igw.id
  }

  tags = {
    Name = "onyx-wl-rt"
  }
}

resource "aws_route_table_association" "onyx_wl_rta" {
  subnet_id      = aws_subnet.onyx_wl_subnet.id
  route_table_id = aws_route_table.onyx_wl_rt.id
}

resource "aws_security_group" "onyx_wl_sg" {
  name        = "allow inbound access"
  description = "Allow Inbound Access"
  vpc_id      = aws_vpc.onyx_wl_vpc.id

  ingress {
    cidr_blocks = ["10.0.1.0/24"]
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
  }

  egress {
    cidr_blocks = ["0.0.0.0/0"]
    from_port   = 1
    to_port     = 65535
    protocol    = "tcp"
  }

  tags = {
    "Name" = "Cluster Web Public Security Group"
  }
}

resource "aws_instance" "onyx_wl_node" {
  # ami                   = data.aws_ami.onyx_wl_ami.id
  ami           = "ami-0012689434fa97f62"
  instance_type = "m7g.xlarge"

  vpc_security_group_ids = [aws_security_group.onyx_wl_sg.id]
  subnet_id              = aws_subnet.onyx_wl_subnet.id
  private_ip             = "10.0.1.12"

  tags = {
    Name = "Cluster Master Node"
  }
}

resource "aws_eip" "onyx_wl_eip" {
  domain                    = "vpc"
  instance                  = aws_instance.onyx_wl_node.id
  associate_with_private_ip = "10.0.1.12"
  depends_on                = [aws_internet_gateway.onyx_wl_igw]

  tags = {
    Name = "onyx-wl-eip"
  }
}

resource "aws_eip_association" "onyx_wl_eip_assoc" {
  instance_id   = aws_instance.onyx_wl_node.id
  allocation_id = aws_eip.onyx_wl_eip.id
}

/*
resource "aws_route" "master_internet_route" {
  destination_cidr_block = "0.0.0.0/0"
  route_table_id         = aws_route_table.onyx_wl_rt.id
  gateway_id             = aws_internet_gateway.onyx_wl_igw.id
}
*/

/*
data "aws_ami" "onyx_wl_ami" {
  most_recent = true

  filter {
    name    = "name"
    # values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"]
    values  = ["ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  owners = ["483285841698"] # Canonical
}
*/

# For EC2 Instance
/*
  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -o xtrace
    /etc/eks/bootstrap.sh ${var.cluster_name}
  EOF
  )
  */

/*
  tag_specifications {
    resource_type = "instance"
    tags          = {
      Name = "${var.cluster_name}-master"
    }
  }
  */