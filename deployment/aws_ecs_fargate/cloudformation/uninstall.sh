#!/bin/bash

ENVIRONMENT="${ENVIRONMENT:-production}"
AWS_REGION="${AWS_REGION:-us-west-1}"
S3_BUCKET="${S3_BUCKET:-onyx-ecs-fargate-configs}"

STACK_NAMES=(
  "${ENVIRONMENT}-onyx-nginx-service"
  "${ENVIRONMENT}-onyx-web-server-service"
  "${ENVIRONMENT}-onyx-backend-background-server-service"
  "${ENVIRONMENT}-onyx-backend-api-server-service"
  "${ENVIRONMENT}-onyx-model-server-inference-service"
  "${ENVIRONMENT}-onyx-model-server-indexing-service"
  "${ENVIRONMENT}-onyx-vespaengine-service"
  "${ENVIRONMENT}-onyx-redis-service"
  "${ENVIRONMENT}-onyx-postgres-service"
  "${ENVIRONMENT}-onyx-cluster"
  "${ENVIRONMENT}-onyx-efs"
  )

delete_stack() {
  local stack_name=$1

  if [ "$stack_name" == "${ENVIRONMENT}-onyx-cluster" ]; then
      echo "Removing all objects and directories from the onyx config s3 bucket."
      aws s3 rm "s3://${ENVIRONMENT}-${S3_BUCKET}" --recursive
      sleep 5
  fi

  echo "Deleting stack: $stack_name..."
  aws cloudformation delete-stack \
    --stack-name "$stack_name" \
    --region "$AWS_REGION"

  echo "Waiting for stack $stack_name to be deleted..."
  aws cloudformation wait stack-delete-complete \
    --stack-name "$stack_name" \
    --region "$AWS_REGION"

  if [ $? -eq 0 ]; then
    echo "Stack $stack_name deleted successfully."
    sleep 10
  else
    echo "Failed to delete stack $stack_name. Exiting."
    exit 1
  fi
}

for stack_name in "${STACK_NAMES[@]}"; do
  delete_stack "$stack_name"
done

echo "All stacks deleted successfully."
