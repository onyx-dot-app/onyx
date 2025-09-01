#!/bin/bash

cd ../src/aws/

# tofu destroy
#
tofu destroy -auto-approve
if [ $? -eq 0 ]; then
    echo "#                                                                                           #"
    echo "#                                                                                           #"
    echo "#############################################################################################"
    echo "#                                                                                           #"
    echo "############# tofu destroy SUCCEEDED!  Onyx Whitelabel Infra on AWS Destroyed! ##############"
    echo "#                                                                                           #"
    echo "#############################################################################################"
fi
