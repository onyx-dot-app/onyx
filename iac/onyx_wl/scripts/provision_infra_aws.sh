#!/bin/bash

cd ../src/aws/

tofu init
if [ $? -ne 0 ]; then
    echo "#                                                                                           #"
    echo "#                                                                                           #"
    echo "#############################################################################################"
    echo "#                                                                                           #"
    echo "############################# tofu init FAILED! Try again... ################################"
    echo "#                                                                                           #"
    echo "#############################################################################################"
fi

tofu fmt

tofu validate

# tofu plan -out onyx_wl_plan
#
tofu plan

# tofu test

# tofu apply
# tofu apply onyx_wl_plan
# tofu apply onyx_wl_plan -auto-approve

tofu apply -auto-approve
if [ $? -ne 0 ]; then
    echo "#                                                                                           #"
    echo "#                                                                                           #"
    echo "#############################################################################################"
    echo "#                                                                                           #"
    echo "############### tofu apply FAILED! Destroying PARTIAL infra provisioning... #################"
    echo "#                                                                                           #"
    echo "#############################################################################################"
    
    tofu destroy -auto-approve
else
    echo "#                                                                                           #"
    echo "#                                                                                           #"
    echo "#############################################################################################"
    echo "#                                                                                           #"
    echo "################# tofu apply SUCCEEDED! Infra Created for Onyx WL on AWS! ###################"
    echo "#                                                                                           #"
    echo "#############################################################################################"
fi
