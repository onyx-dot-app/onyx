.PHONY: craft-connect craft-intercept craft-ready craft-ready-infra craft-api craft-up craft-down craft-pause craft-resume craft-doctor craft-disk craft-clean craft-migrate craft-migration-status craft-sandbox-image craft-backend-image craft-refresh-images craft-check-images

CLUSTER_NAME ?= onyx-dev
NAMESPACE ?= onyx
DEV = python3 deployment/helm/dev/dev.py --cluster-name $(CLUSTER_NAME) --namespace $(NAMESPACE)

craft-up:
	deployment/helm/dev/craft-up.sh --cluster-name $(CLUSTER_NAME) --namespace $(NAMESPACE)

craft-down:
	deployment/helm/dev/craft-down.sh --cluster-name $(CLUSTER_NAME) --namespace $(NAMESPACE)

craft-pause:
	$(DEV) pause

craft-resume:
	$(DEV) resume

craft-disk:
	$(DEV) disk

craft-doctor:
	$(DEV) doctor

# Preview only. Pass CLEAN_ARGS=--apply to remove listed checkout images.
craft-clean:
	$(DEV) clean $(CLEAN_ARGS)

craft-migrate:
	.venv/bin/python deployment/helm/dev/dev.py --cluster-name $(CLUSTER_NAME) --namespace $(NAMESPACE) migrate upgrade

craft-migration-status:
	.venv/bin/python deployment/helm/dev/dev.py --cluster-name $(CLUSTER_NAME) --namespace $(NAMESPACE) migrate status

craft-sandbox-image:
	$(DEV) images --only sandbox

# Rebuild the image the in-cluster sandbox-proxy/api-server run, then restart them.
craft-backend-image:
	$(DEV) images --only backend

# Refresh everything: backend + sandbox images, PodTemplate, proxy/api restart.
craft-refresh-images:
	$(DEV) images

craft-check-images:
	$(DEV) images --check

craft-connect:
	$(DEV) connect

craft-intercept:
	$(DEV) intercept

craft-ready-infra:
	$(DEV) ready --stage infrastructure

craft-ready:
	$(DEV) ready

craft-api: craft-intercept
	.venv/bin/python deployment/helm/dev/launch.py --cluster-name $(CLUSTER_NAME) --namespace $(NAMESPACE) api
