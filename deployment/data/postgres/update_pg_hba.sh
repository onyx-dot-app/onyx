#!/bin/bash

dirname=$(dirname -- "$0")
PG_HBA_CONF_TEMPLATE="${dirname}/pg_hba.conf.template" # Input template file
PG_HBA_CONF_OUTPUT="${dirname}/pg_hba.conf"           # Output file

if [ -z "${ECS_FARGATE_VPC_CIDR}" ]; then
	echo "Missing ECS_FARGATE_VPC_CIDR env variable"
	exit 1
fi

echo "Substituting CIDR block into pg_hba.conf..."
if [ ! -f "$PG_HBA_CONF_TEMPLATE" ]; then
  echo "Error: Template file $PG_HBA_CONF_TEMPLATE not found. Exiting."
  exit 1
fi

envsubst < "$PG_HBA_CONF_TEMPLATE" > "$PG_HBA_CONF_OUTPUT"

echo "pg_hba.conf updated successfully. Output file: $PG_HBA_CONF_OUTPUT"
