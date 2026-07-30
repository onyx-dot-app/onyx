Documentation for how to deploy Onyx can be found in our official docs:
https://docs.onyx.app/deployment/overview

## Maintaining the compose files (contributors)

`docker_compose/docker-compose.yml`, `docker-compose.prod.yml` and
`docker-compose.prod-no-letsencrypt.yml` are generated from the single source of truth
`docker_compose/docker-compose.template.yml` — do not hand-edit them. To change any of the three,
edit the template (per-variant differences are expressed with `#!for` / `#!only` / `#!value`
directives, documented in `ods generate-compose --help`) and regenerate:

```
ods generate-compose --write
```

The generator lives in `tools/ods` (`internal/composegen`) and ships with the `onyx-devtools`
package. The `docker-compose-sync` pre-commit hook runs it automatically for commits touching the
template or the generated files, so a stray edit to a generated file gets reverted on the next
commit.

onyx-cli embeds copies of the guided-install deployment files (the generated
`docker-compose.yml` and `docker-compose.prod.yml`, the lite/craft overlays, the env templates,
the nginx config, and `docker_compose/README.md`) under
`cli/internal/deploy/deployfiles/embedded/`. The same `ods generate-compose --write` run refreshes
them after rendering the variants, and a drift test in the cli module (`go test ./...`) gates
staleness. If you change any of those files, re-run the generator and commit the refreshed embedded
copies.

Note that `docker_compose/README.md` ships inside every self-hosted install, so keep it
user-facing — contributor notes like this one belong here instead.
