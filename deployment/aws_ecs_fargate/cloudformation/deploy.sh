#!/bin/bash

# Function to remove comments from JSON and output valid JSON
remove_comments() {
    sed 's/\/\/.*$//' "$1" | grep -v '^[[:space:]]*$'
}

# Variables
TEMPLATE_DIR="$(pwd)"
SERVICE_DIR="$TEMPLATE_DIR/services"

# Unified config file
CONFIG_FILE="onyx_config.jsonl"

# Try to get AWS_REGION from config, fallback to default if not found
AWS_REGION_FROM_CONFIG=$(remove_comments "$CONFIG_FILE" | jq -r '.AWSRegion // empty')
if [ -n "$AWS_REGION_FROM_CONFIG" ]; then
    AWS_REGION="$AWS_REGION_FROM_CONFIG"
else
    AWS_REGION="${AWS_REGION:-us-east-2}"
fi

# Get environment from config file
ENVIRONMENT=$(remove_comments "$CONFIG_FILE" | jq -r '.Environment')
if [ -z "$ENVIRONMENT" ] || [ "$ENVIRONMENT" == "null" ]; then
    echo "Missing Environment in $CONFIG_FILE. Please add the Environment field."
    exit 1
fi

# Try to get S3_BUCKET from config, fallback to default if not found
S3_BUCKET_FROM_CONFIG=$(remove_comments "$CONFIG_FILE" | jq -r '.S3Bucket // empty')
if [ -n "$S3_BUCKET_FROM_CONFIG" ]; then
    S3_BUCKET="$S3_BUCKET_FROM_CONFIG"
else
    S3_BUCKET="${S3_BUCKET:-onyx-ecs-fargate-configs}"
fi

INFRA_ORDER=(
  "onyx_efs_template.yaml"
  "onyx_cluster_template.yaml"
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

# Function to create CloudFormation parameters from JSON
create_parameters_from_json() {
  local template_file=$1
  local temp_params_file="${template_file%.yaml}_parameters.json"
  
  # Convert the config file contents to CloudFormation parameter format
  echo "[" > "$temp_params_file"
  
  # Process all key-value pairs from the config file
  local first=true
  remove_comments "$CONFIG_FILE" | jq -r 'to_entries[] | select(.value != null and .value != "") | "\(.key)|\(.value)"' | while IFS='|' read -r key value; do
    if [ "$first" = true ]; then
      first=false
    else
      echo "," >> "$temp_params_file"
    fi
    echo "    {\"ParameterKey\": \"$key\", \"ParameterValue\": \"$value\"}" >> "$temp_params_file"
  done
  
  echo "]" >> "$temp_params_file"
  
  # Debug output - display the created parameters file
  echo "Generated parameters file: $temp_params_file" >&2
  echo "Contents:" >&2
  cat "$temp_params_file" >&2
  
  # Return just the filename
  echo "$temp_params_file"
}

# Function to deploy a CloudFormation stack
deploy_stack() {
  local stack_name=$1
  local template_file=$2

  echo "Checking if stack $stack_name exists..."
  if aws cloudformation describe-stacks --stack-name "$stack_name" --region "$AWS_REGION" > /dev/null 2>&1; then
    echo "Stack $stack_name already exists. Skipping deployment."
    return 0
  fi
  
  # Create temporary parameters file for this template
  local temp_params_file=$(create_parameters_from_json "$template_file")
  
  # Special handling for SubnetIDs parameter if needed
  if grep -q "SubnetIDs" "$template_file"; then
    echo "Template uses SubnetIDs parameter, ensuring it's properly formatted..."
    # Make sure we're passing SubnetIDs as a comma-separated list
    local subnet_ids=$(remove_comments "$CONFIG_FILE" | jq -r '.SubnetIDs // empty')
    if [ -n "$subnet_ids" ]; then
      echo "Using SubnetIDs from config: $subnet_ids"
    else
      echo "Warning: SubnetIDs not found in config but template requires it."
    fi
  fi
  
  echo "Deploying stack: $stack_name with template: $template_file and generated config from: $CONFIG_FILE..."
  aws cloudformation deploy \
    --stack-name "$stack_name" \
    --template-file "$template_file" \
    --parameter-overrides file://"$temp_params_file" \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
    --region "$AWS_REGION" \
    --no-cli-auto-prompt > /dev/null

  if [ $? -ne 0 ]; then
    echo "Error: Deployment failed for $stack_name. Exiting."
    exit 1
  fi
  
  # Clean up temporary parameter file
  rm "$temp_params_file"
  
  echo "Stack deployed successfully: $stack_name."
}

convert_underscores_to_hyphens() {
  local input_string="$1"
  local converted_string="${input_string//_/-}"
  echo "$converted_string"
}

deploy_infra_stacks() {
    for template_name in "${INFRA_ORDER[@]}"; do
      # Skip ACM template if HostedZoneId is not set
      if [[ "$template_name" == "onyx_acm_template.yaml" ]]; then
        HOSTED_ZONE_ID=$(remove_comments "$CONFIG_FILE" | jq -r '.HostedZoneId')
        if [ -z "$HOSTED_ZONE_ID" ] || [ "$HOSTED_ZONE_ID" == "" ] || [ "$HOSTED_ZONE_ID" == "null" ]; then
          echo "Skipping ACM template deployment because HostedZoneId is not set in $CONFIG_FILE"
          continue
        fi
      fi

      template_file="$template_name"
      stack_name="$ENVIRONMENT-$(basename "$template_name" _template.yaml)"
      stack_name=$(convert_underscores_to_hyphens "$stack_name")

      if [ -f "$template_file" ]; then
        validate_template "$template_file"
        deploy_stack "$stack_name" "$template_file"
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

      if [ -f "$template_file" ]; then
        validate_template "$template_file"
        deploy_stack "$stack_name" "$template_file"
      else
        echo "Warning: Template file $template_file not found. Skipping."
      fi
    done
}

echo "Starting deployment of Onyx to ECS Fargate Cluster..."
deploy_infra_stacks
deploy_services_stacks

echo "All templates validated and deployed successfully."
