#!/bin/bash

# Variables
ECS_FARGATE_VPC_CIDR=$1
if [ -z "$ECS_FARGATE_VPC_CIDR" ]; then
    echo "Missing the  required vpc cidr argument.  Example: ./deploy.sh 172.30.0.0/16"
    exit 1
fi

AWS_REGION="${AWS_REGION:-us-west-1}"
TEMPLATE_DIR="$(pwd)"
SERVICE_DIR="$TEMPLATE_DIR/services"
ENVIRONMENT="${ENVIRONMENT:-production}"
S3_BUCKET="${S3_BUCKET:-onyx-ecs-fargate-configs}"

INFRA_ORDER=(
  "onyx_efs_template.yaml"
  "onyx_cluster_template.yaml"
  "onyx_lambda_cron_restart_services_template.yaml"
  "onyx_acm_template.yaml"
)

# Deployment order for services
SERVICE_ORDER=(
  "onyx_postgres_service_template.yaml"
  "onyx_redis_service_template.yaml"
  "onyx_vespaengine_service_template.yaml"
  "onyx_model_server_indexing_service_template.yaml"
  "onyx_model_server_inference_service_template.yaml"
  "onyx_backend_api_server_service_template.yaml"
  "onyx_backend_background_server_service_template.yaml"
  "onyx_web_server_service_template.yaml"
  "onyx_nginx_service_template.yaml"
)

# JSON file mapping for services
COMMON_PARAMETERS_FILE="$SERVICE_DIR/onyx_services_parameters.json"
NGINX_PARAMETERS_FILE="$SERVICE_DIR/onyx_nginx_parameters.json"
EFS_PARAMETERS_FILE="onyx_efs_parameters.json"
ACM_PARAMETERS_FILE="onyx_acm_parameters.json"
CLUSTER_PARAMETERS_FILE="onyx_cluster_parameters.json"
LAMBDA_PARAMETERS_FILE="onyx_lambda_cron_restart_services_parameters.json"

# Function to validate a CloudFormation template
validate_template() {
  local template_file=$1
  echo "Validating template: $template_file..."
  aws cloudformation validate-template --template-body file://"$template_file" --region "$AWS_REGION" > /dev/null
  if [ $? -ne 0 ]; then
    echo "Error: Validation failed for $template_file. Exiting."
    exit 1
  fi
  echo "Validation succeeded for $template_file."
}

# Function to deploy a CloudFormation stack
deploy_stack() {
  local stack_name=$1
  local template_file=$2
  local config_file=$3

  echo "Checking if stack $stack_name exists..."
  if aws cloudformation describe-stacks --stack-name "$stack_name" --region "$AWS_REGION" > /dev/null 2>&1; then
    echo "Stack $stack_name already exists. Skipping deployment."
    return 0
  fi

  echo "Deploying stack: $stack_name with template: $template_file and config: $config_file..."
  if [ -f "$config_file" ]; then
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$template_file" \
      --parameter-overrides file://"$config_file" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
      --region "$AWS_REGION" \
      --no-cli-auto-prompt > /dev/null
  else
    echo "Missing required parameter json file"
	exit 1
  fi

  if [ $? -ne 0 ]; then
    echo "Error: Deployment failed for $stack_name. Exiting."
    exit 1
  fi
  echo "Stack deployed successfully: $stack_name."
}

convert_underscores_to_hyphens() {
  local input_string="$1"
  local converted_string="${input_string//_/-}"
  echo "$converted_string"
}

deploy_infra_stacks() {
    for template_name in "${INFRA_ORDER[@]}"; do
      template_file="$template_name"
      stack_name="$ENVIRONMENT-$(basename "$template_name" _template.yaml)"
      stack_name=$(convert_underscores_to_hyphens "$stack_name")

      # Use the common parameters file for specific services
      if [[ "$template_name" =~ ^(onyx_cluster_template.yaml)$ ]]; then
        config_file="$CLUSTER_PARAMETERS_FILE"
      elif [[ "$template_name" =~ ^(onyx_efs_template.yaml)$ ]]; then
        config_file="$EFS_PARAMETERS_FILE"
      elif [[ "$template_name" =~ ^(onyx_acm_template.yaml)$ ]]; then
          config_file="$ACM_PARAMETERS_FILE"
      elif [[ "$template_name" =~ ^(onyx_lambda_cron_restart_services_template.yaml)$ ]]; then
          config_file="$LAMBDA_PARAMETERS_FILE"
      else
          config_file=""
      fi

      if [ -f "$template_file" ]; then
        validate_template "$template_file"
        deploy_stack "$stack_name" "$template_file" "$config_file"
        if [[ "$template_name" =~ ^(onyx_cluster_template.yaml)$ ]]; then
            echo "s3 bucket now exists, copying nginx and postgres configs to s3 bucket"
            ECS_FARGATE_VPC_CIDR=${ECS_FARGATE_VPC_CIDR} ../../data/postgres/update_pg_hba.sh
            aws s3 cp ../../data/postgres/pg_hba.conf "s3://${ENVIRONMENT}-${S3_BUCKET}/postgres/"
            aws s3 cp ../../data/nginx/ "s3://${ENVIRONMENT}-${S3_BUCKET}/nginx/" --recursive
        fi
      else
        echo "Warning: Template file $template_file not found. Skipping."
      fi
    done
}

deploy_services_stacks() { 
    for template_name in "${SERVICE_ORDER[@]}"; do
      template_file="$SERVICE_DIR/$template_name"
      stack_name="$ENVIRONMENT-$(basename "$template_name" _template.yaml)"
      stack_name=$(convert_underscores_to_hyphens "$stack_name")

      # Use the common parameters file for specific services
      if [[ "$template_name" =~ ^(onyx_backend_api_server_service_template.yaml|onyx_postgres_service_template.yaml|onyx_backend_background_server_service_template.yaml|onyx_redis_service_template.yaml|onyx_model_server_indexing_service_template.yaml|onyx_model_server_inference_service_template.yaml|onyx_vespaengine_service_template.yaml|onyx_web_server_service_template.yaml)$ ]]; then
        config_file="$COMMON_PARAMETERS_FILE"
      elif [[ "$template_name" =~ ^(onyx_nginx_service_template.yaml)$ ]]; then
        config_file="$NGINX_PARAMETERS_FILE"
      else
          config_file=""
      fi

      if [ -f "$template_file" ]; then
        validate_template "$template_file"
        deploy_stack "$stack_name" "$template_file" "$config_file"
      else
        echo "Warning: Template file $template_file not found. Skipping."
      fi
    done
}

echo "Starting deployment of Onyx to ECS Fargate Cluster..."
deploy_infra_stacks
deploy_services_stacks

echo "All templates validated and deployed successfully."
