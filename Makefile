.PHONY: craft-up craft-down craft-sandbox-image

craft-up:
	deployment/helm/dev/craft-up.sh

craft-down:
	deployment/helm/dev/craft-down.sh

craft-sandbox-image:
	docker build -t onyxdotapp/sandbox:dev backend/onyx/server/features/build/sandbox/kubernetes/docker
	kind load docker-image onyxdotapp/sandbox:dev --name onyx-dev
