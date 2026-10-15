.PHONY: craft-up craft-down craft-sandbox-image craft-backend-image craft-refresh-images craft-check-images

craft-up:
	deployment/helm/dev/craft-up.sh

craft-down:
	deployment/helm/dev/craft-down.sh

craft-sandbox-image craft-backend-image: craft-refresh-images

craft-refresh-images:
	deployment/helm/dev/refresh-images.sh

craft-check-images:
	deployment/helm/dev/refresh-images.sh --check
