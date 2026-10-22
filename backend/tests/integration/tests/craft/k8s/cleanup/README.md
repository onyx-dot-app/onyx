# Kubernetes cleanup resource checks

These tests exercise real Kubernetes deletion behavior without changing the application database.
Each test creates a namespace and removes only that namespace's resources.
Teardown releases test finalizers and deletes the namespace with a UID precondition.
The tests do not use mocks or require an application login.

Run from the repository root against the deployment under test:

```sh
SANDBOX_BACKEND=kubernetes K8S_CONTEXT=onyx-craft-dev \
uv run pytest backend/tests/integration/tests/craft/k8s/cleanup -v
```

Set `SANDBOX_CONTAINER_IMAGE` to the deployment's sandbox image when it is not the default.
The Kubernetes CI workflow discovers these files and runs each in its own deployment shard.
