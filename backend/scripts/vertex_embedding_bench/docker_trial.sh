#!/usr/bin/env bash
# Run one bench.py trial in a container with pod CPU and memory limits.
# Usage: docker_trial.sh CPUS MEM_GB LABEL [bench.py args...]
# Start the mock on the host first (README.md, "Container trials").
# Environment:
#   IMAGE      image to run (default onyx-backend:vertex-bench, see Dockerfile.bench)
#   MOCK_PORT  port of the mock on the host (default 8799)
#   PYTHON     host Python with the Onyx backend requirements (default python)
set -euo pipefail
if [ $# -lt 3 ]; then
  echo "usage: $0 CPUS MEM_GB LABEL [bench.py args...]" >&2
  exit 2
fi
cpus=$1
mem=$2
label=$3
shift 3
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
rel=${here#"$repo"/}
image=${IMAGE:-onyx-backend:vertex-bench}
port=${MOCK_PORT:-8799}
# The container has no git, so pass the host's git info.
gi=$(cd "$here" && PYTHONPATH="" "${PYTHON:-python}" -c \
  "import bench, json; print(json.dumps(bench.git_info()))")
docker run --rm --cpus="$cpus" --memory="${mem}g" --memory-swap="${mem}g" \
  -v "$repo":/wt -e PYTHONPATH=/wt/backend -e BENCH_GIT_INFO="$gi" \
  -w "/wt/$rel" --entrypoint python "$image" \
  bench.py --mock-url "http://host.docker.internal:$port" --sa-host host.docker.internal \
  --mem-limit-gb "$mem" --results results_docker.jsonl --label "${label}_cpu${cpus}" "$@"
