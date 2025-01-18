#!/bin/bash

# Variables
AWS_REGION="us-west-1"              # AWS region
TEMPLATE_DIR="$(pwd)"               # Base directory containing YAML templates
SERVICE_DIR="$TEMPLATE_DIR/services" # Services directory
ENVIRONMENT="${ENVIRONMENT:-production}"           # Prefix for CloudFormation stack names

INFRA_ORDER=(
  "onyx_efs_template.yaml"
  "onyx_cluster_template.yaml"
  "onyx_lambda_cron_restart_services_template.yaml"
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
EFS_PARAMETERS_FILE="$SERVICE_DIR/onyx_efs_parameters.json"
ACM_PARAMETERS_FILE="$SERVICE_DIR/onyx_acm_parameters.json"
CLUSTER_PARAMETERS_FILE="$SERVICE_DIR/onyx_cluster_parameters.json"

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

  echo "Deploying stack: $stack_name with template: $template_file and config: $config_file..."
  if [ -n "$config_file" ] && [ -f "$config_file" ]; then
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$template_file" \
      --parameter-overrides file://"$config_file" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
      --region "$AWS_REGION" \
      --no-cli-auto-prompt > /dev/null
  else
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$template_file" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
      --region "$AWS_REGION" > /dev/null
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
        echo "s3 bucket now exists, copying nginx and postgres configs to s3 bucket"
        aws s3 cp ../../deployment/data/postgres/pg_hba.conf s3://${ENVIRONMENT}-onyx-ecs-fargate-configs/postgres/
        aws s3 cp ../../deployment/data/nginx/ s3://${ENVIRONMENT}-onyx-ecs-fargate-configs/nginx/ --recursive
      elif [[ "$template_name" =~ ^(onyx_efs_template.yaml)$ ]]; then
        config_file="$EFS_PARAMETERS_FILE"
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
