# PR #16376 review guide

[Pull request](https://github.com/onyx-dot-app/onyx/pull/16376) · [Reviewed commit](https://github.com/onyx-dot-app/onyx/commit/6ec086b51a503b74012c5e8d4716f1a2f11fff6c)

This export covers the core implementation at the linked commit. The audit fix below follows that commit.
The guide explains the change; it is not an approval or a CI result.

## 1. Local launches inherit the deployed cluster configuration

Previously, Make and VS Code maintained separate launch commands and depended on a copied environment file. The shared runtime now resolves the API deployment’s ConfigMaps, Secrets, and environment entries in memory, then applies personal overrides; the launch wrapper uses that result for API and worker processes. This gives startup and migration commands one view of the selected cluster’s settings.

**Review focus:** Personal `.env.k8s` entries still take precedence over deployed settings, except that cluster identity and sandbox settings are set from the selected cluster. This is a meaningful change to how local configuration is resolved.

- [Resolve the API deployment configuration: deployment/helm/dev/runtime.py, lines 74–88](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/runtime.py#L74-L88)

- [Apply personal overrides and cluster settings: deployment/helm/dev/runtime.py, lines 168–192](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/runtime.py#L168-L192)

- [Launch API or Celery with the resolved environment: deployment/helm/dev/launch.py, lines 34–58](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/launch.py#L34-L58)

Related files:

- [.vscode/.env.k8s.template](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/.vscode/.env.k8s.template): Template now supports personal overrides instead of copied deployed values.
- [.vscode/launch.json](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/.vscode/launch.json): API and Celery profiles route through the shared launcher.
- [deployment/helm/dev/tests/test_runtime.py](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/tests/test_runtime.py): Covers configuration precedence, expansion, and keeping secrets out of local files.

**Configuration precedence:** Deployed settings seed the environment, then the personal file overrides them. Cluster context and sandbox backend values are applied afterward.

## 2. Startup waits for infrastructure, then checks the local application

Cluster creation used to finish without waiting for workloads to become usable. Startup now waits for deployed Onyx rollouts and the Telepresence manager, while a separate readiness check verifies the local API through the frontend proxy and then checks the frontend page. This separates cluster readiness from readiness of the locally launched services.

**Review focus:** The startup flow now treats infrastructure readiness and local application readiness as separate milestones; users need to start local services before the latter can pass.

- [Wait for deployed workloads: deployment/helm/dev/runtime.py, lines 250–274](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/runtime.py#L250-L274)

- [Require the selected API intercept: deployment/helm/dev/runtime.py, lines 356–362](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/runtime.py#L356-L362)

- [Probe the API through the frontend: deployment/helm/dev/runtime.py, lines 436–460](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/runtime.py#L436-L460)

Related files:

- [deployment/helm/dev/k8s-up.sh](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/k8s-up.sh): Runs infrastructure readiness after Helm setup.

## 3. Make and VS Code use shared Craft lifecycle commands

The previous VS Code tasks embedded Telepresence setup, migration execution, and cluster operations in task-specific shell commands. Make now exposes those operations through a shared Python command surface, and VS Code tasks call the Make targets; local launch profiles use the shared launcher. The same surface adds diagnostics, pause and resume, migration status, and readiness commands.

- [Select cluster settings and expose lifecycle commands: Makefile, lines 1–15](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/Makefile#L1-L15)

- [Connect, intercept, readiness, and local API targets: Makefile, lines 32–56](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/Makefile#L32-L56)

- [Expose diagnostics, cleanup preview, and readiness in VS Code: .vscode/tasks.json, lines 333–357](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/.vscode/tasks.json#L333-L357)

Related files:

- [deployment/helm/dev/tests/test_dev.py](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/tests/test_dev.py): Covers the development command behavior.

## 4. Image refresh reuses builds and updates future sandbox pods

Previously, image refresh rebuilt both images and updated the sandbox PodTemplate, while image staleness relied on commit timestamps. The new tooling fingerprints source contents, reuses unchanged images, and updates the PodTemplate and relevant deployments when refreshing. Existing sandbox pods keep their current images, so the refresh affects future sandboxes and the refreshed backend workloads.

**Review focus:** Image refresh changes the template for future sandboxes and restarts selected backend workloads, while existing sandbox pods retain their images.

- [Fingerprint tracked and untracked source: deployment/helm/dev/dev.py, lines 53–77](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/dev.py#L53-L77)

- [Reuse, build, and load selected images: deployment/helm/dev/dev.py, lines 124–148](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/dev.py#L124-L148)

- [Reuse the sandbox image during startup: deployment/helm/dev/craft-up.sh, lines 137–147](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/craft-up.sh#L137-L147)

Related files:

- [deployment/helm/dev/refresh-images.sh](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/refresh-images.sh): Delegates image refresh and checks to the shared command.
- [backend/tests/external_dependency_unit/craft_helm/test_sandbox_image_prepuller.py](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/backend/tests/external_dependency_unit/craft_helm/test_sandbox_image_prepuller.py): Checks sandbox callback URL configuration alongside PodTemplate rendering.

**Source-based freshness:** The fingerprint includes source contents and paths, so local edits and untracked files can invalidate an image without relying on commit dates.

## 5. Sandbox callbacks default to the internal API service

Craft previously required an explicit `ONYX_SERVER_URL`, and the local values file pointed callbacks at the host frontend. The chart now derives an internal API Service URL when Craft is enabled, while retaining an explicit configured URL as an override; the sandbox PodTemplate and generated ConfigMap use the same value. The chart version advances to 0.9.20.

**Review focus:** The chart now supplies an internal callback URL by default when Craft is enabled. Deployments that need a public hostname or path prefix still need an explicit override.

- [Select the configured URL or internal API Service: deployment/helm/charts/onyx/templates/_helpers.tpl, lines 288–291](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/charts/onyx/templates/_helpers.tpl#L288-L291)

- [Publish the callback URL in the ConfigMap: deployment/helm/charts/onyx/templates/configmap.yaml, lines 9–11](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/charts/onyx/templates/configmap.yaml#L9-L11)

- [Pass the shared URL to sandbox pods: deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml, lines 29–29](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml#L29-L29)

Related files:

- [deployment/helm/charts/onyx/Chart.yaml](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/charts/onyx/Chart.yaml): Bumps chart version and records the callback URL behavior.
- [deployment/helm/charts/onyx/templates/craft-validation.yaml](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/charts/onyx/templates/craft-validation.yaml): Removes validation requiring an explicit callback URL.
- [deployment/helm/charts/onyx/values.yaml](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/charts/onyx/values.yaml): Documents the default and explicit URL override.
- [deployment/helm/dev/values-localdev.yaml](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/deployment/helm/dev/values-localdev.yaml): Removes the host callback override and sets the sandbox image and pull policy.

## 6. The local guide and feature map describe the new workflow

The development guide and Craft skill now document the shared startup, readiness, image, migration, and cleanup workflow. The feature map adds the Craft sandbox path and component description, and the Helm CI runner receives more disk for its image-heavy test job. The remaining test and documentation changes follow these workflow updates.

- [Craft development skill overview: .agents/skills/onyx-craft-dev/SKILL.md, lines 1–25](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/.agents/skills/onyx-craft-dev/SKILL.md#L1-L25)

Related files:

- [.agents/feature-map/PATHS.md](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/.agents/feature-map/PATHS.md): Maps the new development tooling paths to the Craft sandbox component.
- [.github/workflows/pr-helm-chart-testing.yml](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/.github/workflows/pr-helm-chart-testing.yml): Increases runner disk for Docker and kind image storage.
- [docs/craft/dev/local-kubernetes.md](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/docs/craft/dev/local-kubernetes.md): Reworks the local Kubernetes guide around the shared workflow.

## 7. Other files

Changed files the tour does not otherwise cover.

Related files:

- [.agents/feature-map/components/craft-sandboxes.md](https://github.com/onyx-dot-app/onyx/blob/6ec086b51a503b74012c5e8d4716f1a2f11fff6c/.agents/feature-map/components/craft-sandboxes.md)

## Validation and limits

- Live kind and Telepresence checks covered startup, intercept reuse, hot reload, readiness, doctor, and migrations.
- Three Craft smoke tests covered sandbox provisioning, file upload/readback, and app previews through the frontend.
- 76 Craft Helm tests, 27 workflow tests, Helm lint, type checks, and pre-commit checks passed locally.
- These smoke tests did not call a real LLM.
- Image refresh updates future sandbox pods. Existing pods retain their images and callback settings.
- Retain an existing callback URL override until affected sandboxes are safely removed or recreated.
- The CI disk change requests 100 GB because Docker and kind both retain image data. CI verifies that runner setting.

## Audit follow-up

The PR audit also found an existing Storybook development-server vulnerability,
[GHSA-f2ph-cmg5-wxc8](https://github.com/storybookjs/storybook/security/advisories/GHSA-f2ph-cmg5-wxc8).
This PR upgrades the five pinned Storybook packages from 10.5.0 to the patched 10.6.2 version.
`web/bun.lock` records the matching dependency graph. No audit suppression was added.

The local web audit passes the critical-severity gate. Storybook builds successfully with Bun 1.3.13.
Noncritical findings remain outside this fix. The CI audit checks the full repository and shared allowlist.
