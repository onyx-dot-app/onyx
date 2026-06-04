# Shared helpers for demo scripts. Sourced, not executed.
#
# Each demo script sets DEMO_DESC and takes the sandbox short name as $1
# (e.g. "sandbox-explicit"). Demo exit codes:
#   0  PASS
#   2  SKIP
#   *  FAIL
#
# Runtime: set EGRESS_POC_RUNTIME=kubernetes to run against the k8s manifests
# in k8s/ (kubectl exec). Default is docker (compose containers).

# shellcheck shell=bash

: "${DEMO_DESC:?demo must set DEMO_DESC before sourcing _lib.sh}"
: "${SANDBOX:?demo must set SANDBOX before sourcing _lib.sh}"

EGRESS_POC_RUNTIME="${EGRESS_POC_RUNTIME:-docker}"
EGRESS_POC_NAMESPACE="${EGRESS_POC_NAMESPACE:-egress-poc}"
CONTAINER="egress-poc-${SANDBOX}"
POD="${SANDBOX}"

pass() { printf '  %-4s  %-22s  %s\n' "PASS" "$SANDBOX" "$DEMO_DESC"; exit 0; }
fail() { printf '  %-4s  %-22s  %s  --  %s\n' "FAIL" "$SANDBOX" "$DEMO_DESC" "${1:-}"; exit 1; }
skip() { printf '  %-4s  %-22s  %s  --  %s\n' "SKIP" "$SANDBOX" "$DEMO_DESC" "${1:-}"; exit 2; }

# Real exec; caller gets the workload's exit code unmolested.
dx_real() {
    case "$EGRESS_POC_RUNTIME" in
        docker)
            docker exec "$CONTAINER" "$@"
            ;;
        kubernetes)
            kubectl exec -n "$EGRESS_POC_NAMESPACE" "$POD" -c sandbox -- "$@"
            ;;
        *)
            echo "unknown EGRESS_POC_RUNTIME: $EGRESS_POC_RUNTIME" >&2
            return 2
            ;;
    esac
}

dx() {
    dx_real "$@"
}

# Run in the sandbox; swallow non-zero exit and discard the runtime's own
# diagnostic stderr. The workload-level stderr is captured via 2>&1 INSIDE
# the workload command (see demos that do `sh -c '... 2>&1'`).
#
# Why discard runtime stderr: kubectl prints "command terminated with exit
# code N" to its own stderr on any non-zero, which would contaminate $(...)
# captures (demo 07 saw 'got 407command terminated...' before this fix).
# docker exec doesn't print that, so the behavior is the same in both modes.
dx_safe() {
    dx_real "$@" 2>/dev/null || true
}

is_transparent() {
    [[ "$SANDBOX" == "sandbox-transparent" ]]
}

is_explicit() {
    [[ "$SANDBOX" == "sandbox-explicit" ]]
}
