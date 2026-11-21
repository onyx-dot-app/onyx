# Onyx Docs

The source of [docs.onyx.app](https://docs.onyx.app), built with [Mintlify](https://mintlify.com/). Navigation,
redirects, and site settings live in `docs.json`.

## Preview locally

Needs Node >= 18, `bun`, and the backend Python environment (see the repo `CONTRIBUTING.md`).

```bash
npm i -g mint
cd documentation
scripts/generate.sh   # builds logos/icons from web/lib/opal and openapi.json from the backend
mint dev
```

## Publishing

Production follows the latest stable Onyx release, not `main`. When a release is tagged as the latest stable version,
CI publishes the docs from that release. Changes on `main` ship with the next release.
A docs fix for the current release must also land on its `release/vX.Y` branch.

See `AGENTS.md` for writing rules and checks.
