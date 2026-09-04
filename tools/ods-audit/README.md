# Onyx Devtools Audit

`ods-audit` is the vulnerability auditor of [`ods`](../ods/README.md), the
[onyx.app](https://github.com/onyx-dot-app/onyx) devtools utility script.

It scans lockfiles, container images, open Dependabot alerts, and the GitHub
Actions pinned in `.github` against [OSV.dev](https://osv.dev), and it gates
deploys on the result.

It ships as its own wheel because its scanner is about 50 MB, most of the size
of a combined binary. Install it with the `audit` extra of `onyx-devtools`:

```shell
uv tool install 'onyx-devtools[audit]'
```

Then run it as `ods audit`, which forwards to `ods-audit`, or call `ods-audit`
directly. Both take the same arguments. See the
[`ods audit` documentation](../ods/README.md#audit---audit-dependencies-for-vulnerabilities)
for the full reference.
