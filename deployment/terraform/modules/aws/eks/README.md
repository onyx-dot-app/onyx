# EKS add-ons

## AWS Load Balancer Controller

`aws_load_balancer_controller_chart_version` selects a reviewed chart and IAM configuration:

- `3.6.2` (default): controller v3.6.2, with the missing IAM permissions added to the existing role policy.
- `1.7.1`: controller v2.7.1, retained for staged upgrades of existing clusters.

Blueprints Addons stays at 1.16.3. Other add-on versions and existing Terraform resource addresses stay unchanged.
The extra permissions match the actions absent from its bundled policy:
[controller v3.6.2 IAM policy](https://github.com/kubernetes-sigs/aws-load-balancer-controller/blob/v3.6.2/docs/install/iam_policy.json).
Keep the chart version and these permissions together when updating this module.
Gateway API reconciliation remains disabled. This upgrade preserves Ingress and Service usage.

Controller v2.7.1 can remove native `lifecycle.preStop.sleep` during pod admission.
This blocks pod creation when readiness-gate injection activates its pod webhook.
The Onyx application chart's native sleep handler is valid; upgrade the controller to preserve it.

### Upgrade an existing cluster

1. Review the Terraform plan for the cluster. Confirm it preserves the controller release, service account, and IRSA role.
2. Download the pinned chart: `helm pull aws-load-balancer-controller --repo https://aws.github.io/eks-charts --version 3.6.2 --untar`.
3. Review and apply its `crds/` directory with an explicit Kubernetes context before applying Terraform.
   Helm does not update existing CRDs during an upgrade. Do not use unpinned CRDs from `master`.
4. Apply the reviewed Terraform plan, then wait for both controller replicas to become ready.
5. Submit a pod with native `preStop.sleep` through server-side dry-run in a namespace with readiness-gate injection enabled.
   Confirm the returned pod retains the handler. Do not give the probe the controller's webhook-exclusion label.
6. Deploy the application chart. Confirm new pods become ready and load-balancer targets remain healthy.

See the [v3.6.0 CRD upgrade notes](https://github.com/kubernetes-sigs/aws-load-balancer-controller/releases/tag/v3.6.0).
Gateway API standard CRDs are needed if you later enable Gateway reconciliation; this module leaves it disabled.
