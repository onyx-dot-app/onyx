#!/usr/bin/env bash
# Quota sweep: self-hosted mode, each profile at several concurrency caps.
# Appends to results.jsonl; trial logs go to sweep.log.
# Set PYTHON to a Python with the Onyx backend requirements (default python).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
PYTHONPATH="$(cd "$here/../.." && pwd)${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
py=${PYTHON:-python}
if ! grep -q VERTEXAI_EMBEDDING_MAX_CONCURRENCY "$here/../../shared_configs/configs.py"; then
  echo "This backend does not read VERTEXAI_EMBEDDING_MAX_CONCURRENCY. The sweep needs onyx PR #18315." >&2
  exit 1
fi
cd "$here" || exit 1
for prof in gemini_api_free vertex_free_trial_or_express gemini_api_tier1 vertex_paygo_dsq vertex_paygo_dsq_congested; do
  for k in 1 16 64; do
    "$py" bench.py --profile "$prof" --pod-concurrency 4 --duration 150 --env MULTI_TENANT=false \
      --env VERTEXAI_EMBEDDING_MAX_CONCURRENCY="$k" --label "q_${prof}_k${k}_st" >>sweep.log 2>&1
  done
done
echo SWEEP_DONE >>sweep.log
