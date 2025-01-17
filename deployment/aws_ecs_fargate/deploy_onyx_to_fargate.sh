#!/bin/bash

ENVIRONMENT="${ENVIRONMENT:-production}"

#copy configuration files from github repo to s3 bucket
echo "copyconfig files to s3 bucket"
aws s3 cp ../../deployment/data/postgres/pg_hba.conf s3://${ENVIRONMENT}-onyx-ecs-fargate-configs/postgres/
aws s3 cp ../../deployment/data/nginx/ s3://${ENVIRONMENT}-onyx-ecs-fargate-configs/nginx/conf.d/ --recursive
