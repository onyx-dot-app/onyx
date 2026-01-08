# Helm Chart for Onyx

## Updating Dependencies

When subchart versions are bumped, rebuild the dependency lock file before committing:

```bash
cd deployment/helm/charts/onyx
helm dependency update .
```

---

# Local Testing with Kind

## One-Time Setup

Install [kind](https://kind.sigs.k8s.io/) (Kubernetes in Docker) and create a local cluster:

```bash
# macOS
brew install kind

# Linux (amd64) - see https://kind.sigs.k8s.io/docs/user/quick-start for other architectures
curl -Lo ./kind https://kind.sigs.k8s.io/releases/latest/download/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
```

Create a cluster:

```bash
kind create cluster --name onyx
```

## Automated Testing with chart-testing (ct)

From the repo root, run the chart-testing tool:

```bash
ct install --all --helm-extra-set-args="--set=nginx.enabled=false" --debug --config ct.yaml
```

> **Note:** nginx is disabled because kind lacks LoadBalancer support.

## Render Templates Locally

Preview the rendered Kubernetes manifests without installing:

```bash
cd deployment/helm/charts/onyx
helm template test-output . > test-output.yaml
```

## Manual Cluster Testing

Install the chart into your kind cluster:

```bash
cd deployment/helm/charts/onyx
helm install onyx . -n onyx --create-namespace
```

Forward the nginx service to access the UI locally:

```bash
kubectl -n onyx port-forward service/onyx-nginx 8080:80
```

Then open http://localhost:8080 in your browser.

### Cleanup

Uninstall the release:

```bash
helm uninstall onyx -n onyx
```

PVCs are not automatically deleted. Remove them if you're done testing:

```bash
kubectl -n onyx delete pvc --all
```

Or delete the entire namespace:

```bash
kubectl delete namespace onyx
```

To tear down the kind cluster entirely:

```bash
kind delete cluster --name onyx
```

---

# Configuration

## Running as Non-Root

By default, some containers run as root. To run as a non-root user, add to your `values.yaml`:

For `api`, `webserver`, `indexCapability`, `inferenceCapability`, and `celery_shared`:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1001
```

For `vespa`:

```yaml
podSecurityContext:
  fsGroup: 1000
securityContext:
  privileged: false
  runAsUser: 1000
```

## Resource Tuning

The chart includes resource requests/limits for all Onyx components. These are starting points—tune them based on your workload and cluster capacity.

## Autoscaling

The chart renders **HorizontalPodAutoscalers** by default (`autoscaling.engine: hpa`).

To use **KEDA ScaledObjects** instead:

1. Install the [KEDA operator](https://keda.sh/) separately (it's not bundled with this chart)
2. Set in your `values.yaml`:
   ```yaml
   autoscaling:
     engine: keda
   ```

---

Questions? Reach out on [Slack](https://onyx.app/slack).
