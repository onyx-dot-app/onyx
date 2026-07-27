#!/usr/bin/env bash
# Deepens the shallow checkout left by actions/checkout to complete history.
set -euo pipefail

# Same flags and refspec actions/checkout uses for fetch-depth: 0, with --quiet
# added. Without it git prints one ref-update line per remote ref, which on this
# repo is ~4k lines per job. checkout's show-progress input is no help here: v6
# never passes it through to git fetch, and --progress would not suppress the
# ref summary anyway.
args=(fetch --quiet --no-tags --prune --no-recurse-submodules)

# The checkout is shallow, so --unshallow is what actually restores complete
# history. It also deepens the checked-out ref itself, which matters for pull
# requests from forks: the merge commit's fork-side parent is reachable from no
# refs/heads/* ref.
if [ "$(git rev-parse --is-shallow-repository)" = "true" ]; then
  args+=(--unshallow)
fi

# checkout removes its auth header at the end of its own step unless
# persist-credentials is true, so supply credentials for this fetch. GIT_CONFIG_*
# keeps the token out of both argv and .git/config; adding a second header when
# checkout already left one would send two Authorization headers, hence the
# conditional.
if [ "${CHECKOUT_PERSISTED_CREDENTIALS:-false}" != "true" ]; then
  # Some runners set GITHUB_SERVER_URL with a trailing slash. git's urlmatch
  # does not normalize the resulting "//", so the header would be silently
  # dropped and the fetch would fall back to unauthenticated access.
  server="${GITHUB_SERVER_URL:-https://github.com}"
  basic=$(printf 'x-access-token:%s' "${GIT_FETCH_TOKEN}" | base64 | tr -d '\n')
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0="http.${server%/}/.extraheader"
  export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic ${basic}"
fi

git "${args[@]}" origin \
  '+refs/heads/*:refs/remotes/origin/*' \
  '+refs/tags/*:refs/tags/*'
