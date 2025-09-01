# Instructions for Infra Creation AND Server Side Provisioning

## Provisioning and Cleaning-up of the Onyx WL infra is fully automated. The 2 scripts ```./provision_infra_aws.sh``` and ```./destroy_infra_aws.sh``` can be used in tandem, for speed and repeatability.

### Make sure to always invoke ```./destroy_infra_aws.sh``` after every test session, to clean up AWS infra provisioned by a previous run of ```./provision_infra_aws.sh```. Good luck!

## Infrastructure Provisioning

### 1. Install pre-requisite software for running tofu (provisioning remote infra on aws)

#### a. Install ```aws cli``` - based on your OS

[https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

#### b. Log into AWS with your IAM credentials, generate, and download key-pair (access key and secret key) pair:

[https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/create-key-pairs.html](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/create-key-pairs.html)

#### c. Run the ```aws configure``` command - open the downloaded key-pair .pem file, and copy-paste the keys where requested. Just do the initail part, where 4 inputs are requested.

[https://aws.plainenglish.io/how-to-configure-aws-cli-aws-command-line-interface-77d321a9ba4b](https://aws.plainenglish.io/how-to-configure-aws-cli-aws-command-line-interface-77d321a9ba4b)

#### d. Install opentofu - IaC tool 

[https://opentofu.org/docs/intro/install/](https://opentofu.org/docs/intro/install/)

#### e. Install git
[https://git-scm.com/book/en/v2/Getting-Started-Installing-Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)

### 2. Clone the ```bytedot``` github repo into your local (linux) machine:

[https://github.com/Bytevion-Technologies/bytedot](https://github.com/Bytevion-Technologies/bytedot)

### 3. Run the script to provision the Infra needed for Onyx WhiteLabel Demo:

#### a. Go the the relative path from repo root: ```iac/onyx_wl/scripts/```

#### b. Run the script: ```./provision_infra_aws.sh```

##### This script should provision the needed EC2 instance in your AWS account, since you have already created the key-pair needed for EC2 instances.

##### This also provides the following information, as part of the command-line output (ACTUAL VALUES WOULD VARY!!):

##### i. Public Elastic IP of the EC2 instance: ```elastic_ip_address = "34.232.111.130"```. This IP address is fixed as long as the EC2 instance is running, and is permanently associated with the instance. You can append the required port to this IP and access the desired service running on the EC2 instance.

##### ii. Public Elastic Domain Name of the EC2 Instance: ```elastic_ip_domain_name = "ec2-34-232-111-130.compute-1.amazonaws.com"```. Same as with the Elastic Public IP, but sicne DNS is enabled for the network, a more user-friendly Domain name, with desired port, can be used to access the desired service.

### 4. SSH into the EC2 instance from your local machine, following instructions here (using your local SSH client):

[https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-linux-inst-ssh.html](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-linux-inst-ssh.html)

### 5. Clone the forked (Onyx WL) bytedot GitHub repo into the Ubuntu 24.04 EC2 instance (you're logged into this now):

[[https://github.com/Bytevion-Technologies/bytedot](https://github.com/Bytevion-Technologies/bytedot)]([https://github.com/Bytevion-Technologies/bytedot](https://github.com/Bytevion-Technologies/bytedot))

### 6. Execute instructions to bring up various Onyx WL services as containers (run by docker compose). At each step, when needed, replace ```yum``` with ```apt```:

[https://docs.onyx.app/deployment/deployment_guides/aws/ec2](https://docs.onyx.app/deployment/deployment_guides/aws/ec2)

#### a. Access the desired service via HTTp/HTTPS on a web browser, using the public Elasti IP Address / FQDN along with the ser vice port number, and test out the features manually!

## Cleaning Up The Infrastructure

### 1. Logout of the EC2 instance. You will now enter your local machine command line terminal.

### 2. Go the the path ```iac/onyx_wl/scripts```

### 3. Run the script ```./destroy_infra_aws.sh```. This script successfully destroys all previously provisioned infra for the Onyx WL Demo!