#!/usr/bin/env bash
### Syncs each vendored skills repo in UPSTREAMS into .cursor/skills/<dir>,
### and maintains the top-level symlinks that expose each vendored skill at
### .cursor/skills/<name> (agents discover skills at
### <skills-dir>/<name>/SKILL.md, so a multi-skill repo needs one symlink
### per skill).
###
### To vendor another skills repo, add an UPSTREAMS entry. The next run
### imports it and creates its symlinks.
###
### Run it from anywhere inside the repo with a clean working tree. It
### commits the sync (with the upstream commits in the subject) when an
### upstream changed, and exits quietly when everything is in sync. CI runs
### it weekly via .github/workflows/update-vendored-skills.yml.

set -euo pipefail

# One entry per vendored skills repo: "<dir under .cursor/skills> <url> <ref>".
UPSTREAMS=(
  "greptile https://github.com/greptileai/skills.git main"
)

SKILLS_DIR=".cursor/skills"

cd "$(git rev-parse --show-toplevel)"

# Refuse to mix the sync commit with local changes.
if ! git diff-index --quiet HEAD --; then
  echo "error: working tree has modifications; commit or stash them first" >&2
  exit 1
fi

vendor_dirs=" "
for entry in "${UPSTREAMS[@]}"; do
  read -r dir _ <<<"${entry}"
  vendor_dirs="${vendor_dirs}${dir} "
done

# Bring each vendored directory up to date with its upstream tree.
synced=""
for entry in "${UPSTREAMS[@]}"; do
  read -r dir url ref <<<"${entry}"
  prefix="${SKILLS_DIR}/${dir}"

  git fetch --quiet --no-tags "${url}" "${ref}"
  upstream_commit="$(git rev-parse --short FETCH_HEAD)"
  upstream_tree="$(git rev-parse 'FETCH_HEAD^{tree}')"
  current_tree="$(git rev-parse --quiet --verify "HEAD:${prefix}" || echo none)"

  if [ "${current_tree}" = "${upstream_tree}" ]; then
    echo "${dir}: already in sync with ${url}@${upstream_commit}"
    continue
  fi
  git rm --quiet -r --ignore-unmatch -- "${prefix}"
  git read-tree "--prefix=${prefix}" -u FETCH_HEAD
  synced="${synced}${synced:+, }${dir}@${upstream_commit}"
  echo "${dir}: synced to ${url}@${upstream_commit}"
done

# Drop symlinks whose vendored skill disappeared upstream.
for link in "${SKILLS_DIR}"/*; do
  if [ -L "${link}" ] && [ ! -e "${link}" ]; then
    target="$(readlink -- "${link}")"
    case "${vendor_dirs}" in
      *" ${target%%/*} "*)
        git rm --quiet --ignore-unmatch -- "${link}"
        rm -f -- "${link}"
        ;;
    esac
  fi
done

# Add symlinks for vendored skills that lack one.
for entry in "${UPSTREAMS[@]}"; do
  read -r dir _ <<<"${entry}"
  for skill in "${SKILLS_DIR}/${dir}"/*/; do
    name="$(basename "${skill}")"
    [ -f "${skill}SKILL.md" ] || continue
    link="${SKILLS_DIR}/${name}"
    if [ ! -e "${link}" ] && [ ! -L "${link}" ]; then
      ln -s "${dir}/${name}" "${link}"
      git add -- "${link}"
    elif [ "$(readlink -- "${link}" || true)" != "${dir}/${name}" ]; then
      echo "warning: ${link} is not a symlink to ${dir}/${name}; skipped" >&2
    fi
  done
done

if git diff --cached --quiet; then
  echo "All vendored skills are in sync."
  exit 0
fi

if [ -n "${synced}" ]; then
  subject="chore(skills): sync vendored skills to ${synced}"
else
  subject="chore(skills): update vendored skill symlinks"
fi
git commit --quiet -m "${subject}"
echo "Committed: ${subject}"
