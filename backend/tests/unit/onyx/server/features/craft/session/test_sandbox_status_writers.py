"""Pins the invariant that Craft sandbox status transitions live exclusively
in the lifecycle module (plus the db layer that implements the mutation).

Any new module referencing a sandbox-status mutation helper fails this test
and forces a conscious decision: route the transition through
``sandbox_lifecycle`` instead, or (rarely) extend the allowed set here.
"""

from tests.common.paths import find_ancestor_containing

# The status-mutation surface: the attempt-number-checked transition helpers.
# Any of these constitutes a sandbox-status write.
STATUS_MUTATION_HELPERS: tuple[str, ...] = (
    "begin_provisioning_attempt__no_commit",
    "begin_recovery_attempt__no_commit",
    "finalize_provisioning_attempt__no_commit",
    "sleep_running_sandbox__no_commit",
)

# Modules that MUST reference the status mutation (the spec).
ALLOWED_REFERENCES: set[str] = {
    # Canonical DB mutations.
    "onyx/server/features/build/db/sandbox.py",
    # Substrate-invariant transitions + invariants.
    "onyx/server/features/build/session/sandbox_lifecycle.py",
}


def _modules_referencing_status_mutation() -> set[str]:
    backend_dir = find_ancestor_containing("backend/onyx") / "backend"
    scan_roots = (
        backend_dir / "onyx" / "server" / "features" / "build",
        backend_dir / "onyx" / "background",
    )
    found: set[str] = set()
    for root in scan_roots:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if any(helper in text for helper in STATUS_MUTATION_HELPERS):
                found.add(path.relative_to(backend_dir).as_posix())
    return found


def test_sandbox_status_writers_confined_to_lifecycle_and_db_layer() -> None:
    found = _modules_referencing_status_mutation()

    unexpected = found - ALLOWED_REFERENCES
    assert not unexpected, (
        f"New module(s) reference a sandbox-status mutation helper: "
        f"{sorted(unexpected)}. Sandbox status transitions must go through "
        "onyx/server/features/build/session/sandbox_lifecycle.py."
    )

    missing = ALLOWED_REFERENCES - found
    assert not missing, (
        f"Expected writer(s) no longer reference the mutation: {sorted(missing)}. "
        "Update ALLOWED_REFERENCES if this was intentional."
    )
