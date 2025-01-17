#!/bin/bash

# Variables
AWS_REGION="us-west-1"              # AWS region
TEMPLATE_DIR="$(pwd)"               # Base directory containing YAML templates
SERVICE_DIR="$TEMPLATE_DIR/services" # Services directory
STACK_PREFIX="onyx-stack"           # Prefix for CloudFormation stack names

# Templates deployment order
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

# Mapping of template filenames to JSON config filenames
TEMPLATE_CONFIGS=(
  "onyx_postgres_service_template.yaml:onyx_postgres_service_template.json"
  "onyx_redis_service_template.yaml:onyx_redis_service_template.json"
  "onyx_vespaengine_service_template.yaml:onyx_vespaengine_service_template.json"
  "onyx_model_server_indexing_service_template.yaml:onyx_model_server_indexing_service_template.json"
  "onyx_model_server_inference_service_template.yaml:onyx_model_server_inference_service_template.json"
  "onyx_backend_api_server_service_template.yaml:onyx_backend_api_server_service_template.json"
  "onyx_backend_background_server_service_template.yaml:onyx_backend_background_server_service_template.json"
  "onyx_web_server_service_template.yaml:onyx_web_server_service_template.json"
  "onyx_nginx_service_template.yaml:onyx_nginx_service_template.json"
)

# Function to get the corresponding JSON config for a given template
get_config_file() {
  local template_name=$1
  for mapping in "${TEMPLATE_CONFIGS[@]}"; do
    local template="${mapping%%:*}"
    local config="${mapping##*:}"
    if [ "$template" == "$template_name" ]; then
      echo "$SERVICE_DIR/$config"
      return
    fi
  done
  echo ""
}

# Function to validate a CloudFormation template
validate_template() {
  local template_file=$1
  echo "Validating template: $template_file..."
  aws cloudformation validate-template --template-body file://"$template_file" --region "$AWS_REGION"
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
      --region "$AWS_REGION"
  else
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$template_file" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
      --region "$AWS_REGION"
  fi

  if [ $? -ne 0 ]; then
    echo "Error: Deployment failed for $stack_name. Exiting."
    exit 1
  fi
  echo "Stack deployed successfully: $stack_name."
}

# Deploy the main template first
MAIN_TEMPLATE="$TEMPLATE_DIR/onyx_template.yaml"
validate_template "$MAIN_TEMPLATE"
deploy_stack "$STACK_PREFIX-main" "$MAIN_TEMPLATE" ""

# Deploy each service template in the specified order
for template_name in "${SERVICE_ORDER[@]}"; do
  template_file="$SERVICE_DIR/$template_name"
  config_file=$(get_config_file "$template_name")
  stack_name="$STACK_PREFIX-$(basename "$template_name" .yaml)"

  if [ -f "$template_file" ]; then
    validate_template "$template_file"

    deploy_stack "$stack_name" "$template_file" "$config_file"
  else
    echo "Warning: Template file $template_file not found. Skipping."
  fi
done

echo "All templates validated and deployed successfully."
