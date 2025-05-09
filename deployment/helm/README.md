# Local testing

- One time setup
- brew install kind
- Ensure you have no config at ~/.kube/config
- kind create cluster
- mv ~/.kube/config ~/.kube/kind-config

- Command setup
- export KUBECONFIG=~/.kube/kind-config
- kubectl config use-context kind-kind
- from source root run
- ct install --all --helm-extra-set-args="--set=nginx.enabled=false" --debug --config ct.yaml
