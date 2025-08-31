#!/bin/bash

cd ../src/aws/
# tofu destroy
tofu destroy -auto-approve

echo "#############################################################################################"
echo "#                                                                                           #"
echo "################# Infra provisioned for Onyx Whitelabel on AWS Destroyed! ###################"

cd ../../..
