# Onyx AWS ECS Fargate CloudFormation Deployment

This directory contains CloudFormation templates and scripts to deploy Onyx on AWS ECS Fargate.

## Configuration

All configuration parameters are stored in a single JSON file: `onyx_config.json`. This file contains all the parameters needed for the different CloudFormation stacks.

Example:
```json
{
  "OnyxNamespace": "onyx",
  "Environment": "production",
  "EFSName": "onyx-efs",
  "AWSRegion": "us-east-2",
  "VpcID": "YOUR_VPC_ID",
  "SubnetIDs": "YOUR_SUBNET_ID1,YOUR_SUBNET_ID2",
  "DomainName": "YOUR_DOMAIN e.g ecs.onyx.app",
  "ValidationMethod": "DNS",
  "HostedZoneId": ""
}
```

### Required Parameters

- `Environment`: Used to prefix all stack names during deployment. This is required.
- `OnyxNamespace`: Namespace for the Onyx deployment.
- `EFSName`: Name for the Elastic File System.
- `AWSRegion`: AWS region where resources will be deployed.
- `VpcID`: ID of the VPC where Onyx will be deployed.
- `SubnetIDs`: Comma-separated list of subnet IDs for deployment.
- `DomainName`: Domain name for the Onyx deployment.
- `ValidationMethod`: Method for domain validation (typically "DNS").
- [optional] `HostedZoneId`: Route 53 hosted zone ID (only if using Route 53 for DNS).

The deployment script automatically extracts the needed parameters for each CloudFormation template based on the parameter names defined in the templates.

## Deployment Order

The deployment follows this order:

1. Infrastructure stacks:
   - EFS
   - Cluster
   - ACM

2. Service stacks:
   - Postgres
   - Redis
   - Vespa Engine
   - Model Server (Indexing)
   - Model Server (Inference)
   - Backend API Server
   - Backend Background Server
   - Web Server
   - Nginx

## Usage

To deploy:
```bash
./deploy.sh
```

To uninstall:
```bash
./uninstall.sh
```
