# K8s port of the egress PoC. Mirrors the top-level Makefile (compose) but
# targets a dedicated kind cluster (egress-poc-dev) and the egress-poc namespace.
#
# Usage: from experiments/egress-poc/k8s/, run `make up && make demo`.

SHELL := /bin/bash
CLUSTER_NAME ?= egress-poc-dev
KIND_CONTEXT := kind-$(CLUSTER_NAME)
NAMESPACE := egress-poc
KCTL := kubectl --context $(KIND_CONTEXT) -n $(NAMESPACE)

K8S_DIR := $(CURDIR)
POC_DIR := $(CURDIR)/..

.PHONY: help
help:
	@echo "Targets:"
	@echo "  up                       full bring-up: cluster + images + manifests + wait"
	@echo "  down                     delete the kind cluster (destroys all PoC state)"
	@echo "  demo                     run the 9 demos against both sandboxes via kubectl"
	@echo "  shell-explicit           interactive shell in the sandbox-explicit pod"
	@echo "  shell-transparent        interactive shell in the sandbox-transparent pod"
	@echo "  logs-proxy-explicit      tail proxy sidecar logs (sandbox-explicit pod)"
	@echo "  logs-proxy-transparent   tail proxy sidecar logs (sandbox-transparent pod)"
	@echo "  logs-broker              tail broker logs"
	@echo "  status                   show pod / service / netpol state"
	@echo "  reapply                  re-apply manifests (for iterating on YAML)"

.PHONY: cluster
cluster:
	@if ! kind get clusters 2>/dev/null | grep -qx $(CLUSTER_NAME); then \
		echo "[cluster] creating kind cluster $(CLUSTER_NAME)"; \
		kind create cluster --config $(K8S_DIR)/kind-config.yaml; \
	else \
		echo "[cluster] $(CLUSTER_NAME) already exists"; \
	fi
	kubectl config use-context $(KIND_CONTEXT) >/dev/null

.PHONY: ca
ca:
	@cd $(POC_DIR) && ca/gen-ca.sh

.PHONY: build
build: ca
	@echo "[build] sandbox image (host)"
	@cp $(POC_DIR)/ca/ca.crt $(POC_DIR)/sandbox/ca.crt
	docker build -t egress-poc/sandbox:latest $(POC_DIR)/sandbox
	@echo "[build] proxy / broker / upstream / iptables-init images"
	docker build -t egress-poc/proxy:latest         $(POC_DIR)/proxy
	docker build -t egress-poc/broker:latest        $(POC_DIR)/broker
	docker build -t egress-poc/upstream:latest      $(POC_DIR)/upstream
	docker build -t egress-poc/iptables-init:latest $(POC_DIR)/iptables-init

.PHONY: load
load: build cluster
	@echo "[load] loading images into kind node"
	kind load docker-image egress-poc/sandbox:latest        --name $(CLUSTER_NAME)
	kind load docker-image egress-poc/proxy:latest          --name $(CLUSTER_NAME)
	kind load docker-image egress-poc/broker:latest         --name $(CLUSTER_NAME)
	kind load docker-image egress-poc/upstream:latest       --name $(CLUSTER_NAME)
	kind load docker-image egress-poc/iptables-init:latest  --name $(CLUSTER_NAME)

.PHONY: apply
apply:
	kubectl --context $(KIND_CONTEXT) apply -f $(K8S_DIR)/00-namespace.yaml
	bash $(K8S_DIR)/setup-ca-secret.sh
	kubectl --context $(KIND_CONTEXT) apply -f $(K8S_DIR)/20-broker.yaml
	kubectl --context $(KIND_CONTEXT) apply -f $(K8S_DIR)/30-upstream.yaml
	kubectl --context $(KIND_CONTEXT) apply -f $(K8S_DIR)/70-networkpolicies.yaml
	kubectl --context $(KIND_CONTEXT) apply -f $(K8S_DIR)/50-sandbox-explicit.yaml
	kubectl --context $(KIND_CONTEXT) apply -f $(K8S_DIR)/60-sandbox-transparent.yaml

.PHONY: wait
wait:
	@echo "[wait] broker / upstream deployments"
	$(KCTL) rollout status deployment/broker   --timeout=120s
	$(KCTL) rollout status deployment/upstream --timeout=120s
	@echo "[wait] sandbox pods Ready (each pod boots its own proxy sidecar)"
	$(KCTL) wait --for=condition=Ready pod/sandbox-explicit    --timeout=180s
	$(KCTL) wait --for=condition=Ready pod/sandbox-transparent --timeout=180s

.PHONY: up
up: load apply wait
	@echo ""
	@echo "  [ok] cluster $(CLUSTER_NAME), namespace $(NAMESPACE) ready"
	@echo "  run 'make demo' to exercise the 9 demos"

.PHONY: down
down:
	@if kind get clusters 2>/dev/null | grep -qx $(CLUSTER_NAME); then \
		kind delete cluster --name $(CLUSTER_NAME); \
	else \
		echo "[down] cluster $(CLUSTER_NAME) not present — nothing to delete"; \
	fi

.PHONY: demo
demo:
	@cd $(POC_DIR)/demos && EGRESS_POC_RUNTIME=kubernetes EGRESS_POC_NAMESPACE=$(NAMESPACE) bash runner.sh

.PHONY: shell-explicit
shell-explicit:
	$(KCTL) exec -it sandbox-explicit -c sandbox -- bash

.PHONY: shell-transparent
shell-transparent:
	$(KCTL) exec -it sandbox-transparent -c sandbox -- bash

.PHONY: logs-proxy-explicit
logs-proxy-explicit:
	$(KCTL) logs -f sandbox-explicit -c proxy

.PHONY: logs-proxy-transparent
logs-proxy-transparent:
	$(KCTL) logs -f sandbox-transparent -c proxy

.PHONY: logs-broker
logs-broker:
	$(KCTL) logs -f deployment/broker

.PHONY: status
status:
	@echo "--- pods ---"
	@$(KCTL) get pods -o wide
	@echo ""
	@echo "--- services ---"
	@$(KCTL) get svc
	@echo ""
	@echo "--- networkpolicies ---"
	@$(KCTL) get networkpolicy

.PHONY: reapply
reapply: apply wait
