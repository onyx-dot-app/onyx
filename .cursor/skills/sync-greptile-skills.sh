#!/usr/bin/env bash
### Syncs the vendored .cursor/skills/greptile directory with
### github.com/greptileai/skills, and maintains the top-level symlinks that
### expose each vendored skill at .cursor/skills/<name> (agents discover
### skills at <skills-dir>/<name>/SKILL.md, so a multi-skill repo needs one
### symlink per skill).
###
### Run it from anywhere inside the repo with a clean working tree. It
### commits the sync (with the upstream commit in the subject) when upstream
### changed, and exits quietly when already in sync. CI runs it weekly via
### .github/workflows/update-greptile-skills.yml.

set -euo pipefail

UPSTREAM_URL="https://github.com/greptileai/skills.git"
UPSTREAM_REF="main"
SKILLS_DIR=".cursor/skills"
PREFIX="${SKILLS_DIR}/greptile"

cd "$(git rev-parse --show-toplevel)"

# Refuse to mix the sync commit with local changes.
if ! git diff-index --quiet HEAD --; then
  echo "error: working tree has modifications; commit or stash them first" >&2
  exit 1
fi

git fetch --quiet --no-tags "${UPSTREAM_URL}" "${UPSTREAM_REF}"
upstream_commit="$(git rev-parse --short FETCH_HEAD)"
upstream_tree="$(git rev-parse 'FETCH_HEAD^{tree}')"
current_tree="$(git rev-parse --quiet --verify "HEAD:${PREFIX}" || echo none)"

if [ "${current_tree}" != "${upstream_tree}" ]; then
  git rm --quiet -r --ignore-unmatch -- "${PREFIX}"
  git read-tree "--prefix=${PREFIX}" -u FETCH_HEAD
fi

# Drop symlinks whose vendored skill disappeared upstream.
for link in "${SKILLS_DIR}"/*; do
  if [ -L "${link}" ] && [ ! -e "${link}" ]; then
    case "$(readlink "${link}")" in
      greptile/*)
        git rm --quiet --ignore-unmatch -- "${link}"
        rm -f -- "${link}"
        ;;
    esac
  fi
done

# Add symlinks for skills new upstream.
for skill in "${PREFIX}"/*/; do
  name="$(basename "${skill}")"
  if [ -f "${skill}SKILL.md" ] && [ ! -e "${SKILLS_DIR}/${name}" ]; then
    ln -s "greptile/${name}" "${SKILLS_DIR}/${name}"
    git add -- "${SKILLS_DIR}/${name}"
  fi
done

if git diff --cached --quiet; then
  echo "Already in sync with greptileai/skills@${upstream_commit}."
  exit 0
fi

git commit --quiet \
  -m "chore(skills): sync greptile skills to greptileai/skills@${upstream_commit}"
echo "Committed sync to greptileai/skills@${upstream_commit}."
