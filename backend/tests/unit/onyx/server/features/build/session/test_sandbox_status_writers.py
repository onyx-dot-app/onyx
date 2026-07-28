"""Pins the invariant that Craft sandbox status transitions live exclusively
in the lifecycle module (plus the db layer that implements the mutation).

Any new module referencing ``update_sandbox_status__no_commit`` fails this
test and forces a conscious decision: route the transition through
``sandbox_lifecycle`` instead, or (rarely) extend the allowed set here.
"""

from pathlib import Path

# Modules that MUST reference the status mutation (the spec).
ALLOWED_REFERENCES: set[str] = {
    # Canonical DB mutation.
    "onyx/server/features/build/db/sandbox.py",
    # Substrate-invariant transitions + invariants.
    "onyx/server/features/build/session/sandbox_lifecycle.py",
}


def _modules_referencing_status_mutation() -> set[str]:
    backend_dir = Path(__file__).resolve().parents[7]
    assert backend_dir.name == "backend", (
        f"Unexpected repo layout; expected 'backend', got {backend_dir}"
    )
    scan_roots = (
        backend_dir / "onyx" / "server" / "features" / "build",
        backend_dir / "onyx" / "background",
    )
    found: set[str] = set()
    for root in scan_roots:
        for path in sorted(root.rglob("*.py")):
            if "update_sandbox_status__no_commit" in path.read_text(encoding="utf-8"):
                found.add(path.relative_to(backend_dir).as_posix())
    return found


def test_sandbox_status_writers_confined_to_lifecycle_and_db_layer() -> None:
    found = _modules_referencing_status_mutation()

    unexpected = found - ALLOWED_REFERENCES
    assert not unexpected, (
        "New module(s) reference update_sandbox_status__no_commit: "
        f"{sorted(unexpected)}. Sandbox status transitions must go through "
        "onyx/server/features/build/session/sandbox_lifecycle.py."
    )

    missing = ALLOWED_REFERENCES - found
    assert not missing, (
        f"Expected writer(s) no longer reference the mutation: {sorted(missing)}. "
        "Update ALLOWED_REFERENCES if this was intentional."
    )
