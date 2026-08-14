# Onyx Helm chart repository

This branch hosts the Helm repository index for the Onyx charts. It holds
`index.yaml` and nothing else.

```console
helm repo add onyx https://onyx-dot-app.github.io/onyx
helm install onyx onyx/onyx
```

`.github/workflows/helm-chart-releases.yml` writes `index.yaml` on every chart
release. Do not commit to this branch by hand.

Chart tarballs are GitHub release assets, not files on this branch:

- new versions: the `helm/onyx-<version>` release
- versions published before that change: the [`helm/archive`](https://github.com/onyx-dot-app/onyx/releases/tag/helm/archive) release

Tarballs used to live here. `helm package` records a timestamp, so every
republish wrote new bytes, and git cannot delta-compress a tarball. The branch
reached 102 MiB, which every clone of the repository paid for.
