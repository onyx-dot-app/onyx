# Helm release checker

Changes under `deployment/helm/charts/onyx/` or `deployment/helm/charts/onyx-cnpg-crds/`
require updates in `deployment/helm/charts/onyx/Chart.yaml`:

- Increase `version` above the version on `origin/main`.
- Update the release descriptions under `annotations.artifacthub.io/changes`.
  Describe the chart changes for users. Keep the general chart `description` unchanged
  unless the chart's purpose changes.

The `helm-release` pre-commit hook checks both requirements. Agent stop hooks
also run pre-commit. CI uses the same check for chart pull requests.
The check includes deletions and all files inside both chart directories.
Changes to `deployment/helm/README.md` or `deployment/helm/dev/` alone do not require a chart release.

Run `git fetch origin main` to refresh the local release baseline, then run
`pre-commit run helm-release --all-files`. One update covers all commits in a branch.
Release branches and application release tag builds do not publish charts and are exempt.

Run the regression tests from the repository root:

```bash
uv run --no-project --with PyYAML==6.0.3 --with semver==3.0.4 \
  python -m unittest discover -s tools/helm -v
```

The Helm Chart Version Check workflow also runs these tests when the checker,
its workflow, the pre-commit configuration, or chart files change.
