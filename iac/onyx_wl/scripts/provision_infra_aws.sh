#!/bin/bash

cd ../src/aws/

tofu init
tofu fmt
tofu validate

# tofu plan -out onyx_wl_plan
tofu plan

# tofu test

# tofu apply
# tofu apply onyx_wl_plan
# tofu apply onyx_wl_plan -auto-approve

tofu apply -auto-approve
if [ $? -ne 0 ]; then
    echo "#############################################################################################"
    echo "#                                                                                           #"
    echo "############### tofu apply FAILED! Destroying PARTIAL infra provisioning... #################"
    
    tofu destroy -auto-approve
    
    echo "#############################################################################################"
    echo "#                                                                                           #"
    echo "######################## Wait for 10 minutes before next tofu apply #########################"
else
    echo "#############################################################################################"
    echo "#                                                                                           #"
    echo "################# IaC Provisioning of Infra for Onyx Whitelabel on AWS ! ####################"
fi

# cd ../../..
# . provision_runtime_onyx_wl_ubuntu.sh
