#!/usr/bin/env bash
# Connect the local debugger and recover an unregistered traffic-agent once.
set -euo pipefail

kube() {
  kubectl --context kind-onyx-dev --request-timeout=10s -n onyx "$@"
}

has_stale_agent() {
  local workloads agent_log
  workloads=$(telepresence list --namespace onyx)
  # A registered agent can retain older session errors in its logs.
  if ! printf '%s\n' "$workloads" | grep -Eq '^deployment[[:space:]]+onyx-api-server[[:space:]]*:.*traffic-agent not yet installed'; then
    return 1
  fi
  # Read the latest line from each API sidecar, not historical session errors.
  agent_log=$(kube logs -l 'app=api-server,app.kubernetes.io/instance=onyx' \
    -c traffic-agent --since=2m --tail=1 --prefix=true) || return 1
  printf '%s\n' "$agent_log" | grep -Eq \
    'code = NotFound desc = Session "agent:[^"]+" not found|code = PermissionDenied desc = agent session "agent:[^"]+" is bound to another workload identity'
}

recover_agent() {
  echo 'Telepresence traffic-agent has a stale session; restarting onyx-api-server once.'
  kube rollout restart deployment/onyx-api-server
  kube rollout status deployment/onyx-api-server --timeout=120s --request-timeout=130s
}

create_intercept() {
  telepresence intercept onyx-api-server --namespace onyx --port 8080:8080 --mount=false
}

main() {
  local recovered=false intercept_status
  telepresence connect --context kind-onyx-dev -n onyx
  telepresence leave onyx-api-server 2>/dev/null || true

  if has_stale_agent; then
    recover_agent
    recovered=true
  fi
  if create_intercept; then
    return 0
  else
    intercept_status=$?
  fi

  # The agent can lose its session after the initial check.
  if [[ "$recovered" == false ]] && has_stale_agent; then
    recover_agent
    create_intercept
  else
    return "$intercept_status"
  fi
}

main "$@"
