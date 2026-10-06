#!/usr/bin/env bash
# Exercise recovery without changing a Kubernetes cluster.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
export TEST_DIR
mkdir "$TEST_DIR/bin"

cat > "$TEST_DIR/bin/telepresence" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "telepresence $*" >> "$TEST_DIR/calls"
case "$1" in
  connect) [[ "$SCENARIO" != connect-failure ]] ;;
  leave) exit 0 ;;
  list)
    if [[ "$SCENARIO" == healthy || "$SCENARIO" == historical || -f "$TEST_DIR/recovered" ]]; then
      echo 'deployment onyx-api-server: ready to intercept (traffic-agent already installed)'
    else
      echo 'deployment onyx-api-server: ready to attach (traffic-agent not yet installed)'
    fi
    ;;
  intercept)
    if [[ "$SCENARIO" == unrelated || "$SCENARIO" == historical || "$SCENARIO" == retry-failure || "$SCENARIO" == log-failure || "$SCENARIO" == fallback-retry-failure ]]; then
      if [[ "$SCENARIO" == fallback-retry-failure ]]; then
        touch "$TEST_DIR/attempted"
      fi
      echo 'intercept failed' >&2
      exit 7
    fi
    if [[ "$SCENARIO" == fallback && ! -f "$TEST_DIR/attempted" ]]; then
      touch "$TEST_DIR/attempted"
      echo 'connector.CreateIntercept timed out' >&2
      exit 7
    fi
    echo 'State: ACTIVE'
    ;;
  *) exit 99 ;;
esac
STUB

cat > "$TEST_DIR/bin/kubectl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "kubectl $*" >> "$TEST_DIR/calls"
[[ "$1 $2 $3 $4 $5" == '--context kind-onyx-dev --request-timeout=10s -n onyx' ]] || exit 99
shift 5
case "$1 $2" in
  'logs -l')
    [[ "$SCENARIO" != log-failure ]] || exit 8
    if [[ "$SCENARIO" == unrelated || ( "$SCENARIO" == fallback* && ! -f "$TEST_DIR/attempted" ) ]]; then
      echo 'Connected to Manager 2.31.2'
    elif [[ "$SCENARIO" == permission ]]; then
      echo 'WARN remain: rpc error: code = PermissionDenied desc = agent session "agent:old" is bound to another workload identity'
    else
      echo 'WARN remain: rpc error: code = NotFound desc = Session "agent:old" not found'
    fi
    ;;
  'rollout restart') touch "$TEST_DIR/recovered" ;;
  'rollout status') [[ "$SCENARIO" != rollout-failure ]] ;;
  *) exit 99 ;;
esac
STUB
chmod +x "$TEST_DIR/bin/telepresence" "$TEST_DIR/bin/kubectl"
export PATH="$TEST_DIR/bin:$PATH"

check_scenario() {
  local scenario="$1" expected_status="$2" expected_restarts="$3" expected_intercepts="$4"
  local status=0 restarts intercepts
  export SCENARIO="$scenario"
  rm -f "$TEST_DIR/calls" "$TEST_DIR/recovered" "$TEST_DIR/attempted"
  bash "$SCRIPT_DIR/../telepresence-intercept.sh" > "$TEST_DIR/output" 2>&1 || status=$?
  restarts=$(grep -c 'rollout restart' "$TEST_DIR/calls" || true)
  intercepts=$(grep -c '^telepresence intercept ' "$TEST_DIR/calls" || true)
  if [[ "$status" != "$expected_status" || "$restarts" != "$expected_restarts" || "$intercepts" != "$expected_intercepts" ]]; then
    echo "FAIL $scenario: status=$status restarts=$restarts intercepts=$intercepts"
    cat "$TEST_DIR/output" "$TEST_DIR/calls"
    exit 1
  fi
  if [[ "$expected_restarts" == 1 ]]; then
    grep -q 'rollout status deployment/onyx-api-server --timeout=120s --request-timeout=130s' "$TEST_DIR/calls"
  fi
  echo "PASS $scenario"
}

check_scenario healthy 0 0 1
check_scenario stale 0 1 1
check_scenario permission 0 1 1
check_scenario fallback 0 1 2
check_scenario unrelated 7 0 1
check_scenario historical 7 0 1
check_scenario rollout-failure 1 1 0
check_scenario retry-failure 7 1 1
check_scenario fallback-retry-failure 7 1 2
check_scenario log-failure 7 0 1
check_scenario connect-failure 1 0 0
