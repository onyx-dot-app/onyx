import argparse
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path("backend/openapi.json")
FIX_COMMAND = "python3 backend/lint/check_openapi_snapshot.py --write"


def has_deleted_schema_input() -> bool:
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    diff_range = [f"{from_ref}...{to_ref}"] if from_ref and to_ref else ["--cached"]
    result = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "--no-renames",
            "--diff-filter=D",
            *diff_range,
            "--",
            "backend/onyx/",
            "backend/ee/",
            "backend/shared_configs/",
            "backend/model_server/",
            str(SNAPSHOT),
            "backend/scripts/onyx_openapi_schema.py",
            "backend/lint/check_openapi_snapshot.py",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=ROOT,
    )
    if result.returncode != 1:
        result.check_returncode()
    return result.returncode == 1


def generate(output: Path) -> None:
    backend = ROOT / "backend"
    subprocess.run(
        [
            "uv",
            "run",
            "--no-active",
            "--project",
            str(ROOT),
            "--frozen",
            "--no-default-groups",
            "--group",
            "backend",
            "--group",
            "ee",
            "python",
            "-m",
            "scripts.onyx_openapi_schema",
            "--snapshot",
            "--filename",
            str(output),
        ],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend), "PYTHONNOUSERSITE": "1"},
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the Onyx OpenAPI snapshot")
    parser.add_argument("--write", action="store_true", help="Regenerate the snapshot")
    parser.add_argument("--hook", action="store_true", help="Use prek's file selection")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)

    snapshot = ROOT / SNAPSHOT
    if not (ROOT / "backend/ee/onyx/__init__.py").is_file() and not snapshot.exists():
        return 0  # The FOSS mirror strips both the EE package and the snapshot.
    if args.hook and not args.files and not has_deleted_schema_input():
        return 0

    with TemporaryDirectory(dir=snapshot.parent if args.write else None) as tmp:
        generated = Path(tmp) / "openapi.json"
        generate(generated)
        if args.write:
            generated.replace(snapshot)
            print(f"Updated {SNAPSHOT}.")
            return 0
        if snapshot.is_file() and snapshot.read_bytes() == generated.read_bytes():
            return 0

    print(f"{SNAPSHOT} is out of date. Regenerate it from the repository root:")
    print(f"  {FIX_COMMAND}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
