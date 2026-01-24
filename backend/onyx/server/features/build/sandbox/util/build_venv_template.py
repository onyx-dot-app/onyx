#!/usr/bin/env python3
"""Build sandbox template for Python venv."""

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from onyx.server.features.build.configs import (
        OUTPUTS_TEMPLATE_PATH,
        VENV_TEMPLATE_PATH,
    )
except ImportError:
    # Fallback if running as standalone script
    import os

    OUTPUTS_TEMPLATE_PATH = os.environ.get(
        "OUTPUTS_TEMPLATE_PATH", "/templates/outputs"
    )
    VENV_TEMPLATE_PATH = os.environ.get("VENV_TEMPLATE_PATH", "/templates/venv")


def build_python_venv_template(target_path: Path, requirements_path: Path) -> None:
    """Build Python venv template with required packages.

    Creates a Python virtual environment and installs packages from requirements file.

    Args:
        target_path: Path where the venv should be created
        requirements_path: Path to requirements.txt file

    Raises:
        RuntimeError: If venv creation or package installation fails
    """
    if not requirements_path.exists():
        raise FileNotFoundError(f"Requirements file not found: {requirements_path}")

    # Create venv
    print("  Creating virtual environment...")
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(target_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create virtual environment: {result.stderr}")

    # Determine pip path based on OS
    if sys.platform == "win32":
        pip_path = target_path / "Scripts" / "pip"
    else:
        pip_path = target_path / "bin" / "pip"

    # Install requirements
    print(f"  Installing packages from {requirements_path.name}...")
    install_result = subprocess.run(
        [str(pip_path), "install", "-r", str(requirements_path)],
        capture_output=True,
        text=True,
    )
    if install_result.returncode != 0:
        raise RuntimeError(f"Failed to install packages: {install_result.stderr}")


def main() -> None:
    """Build Python venv template.

    Web template is already provided at backend/onyx/server/features/build/sandbox/templates/web
    """
    parser = argparse.ArgumentParser(
        description="Build Python venv template for sandbox (web template already provided)"
    )
    parser.add_argument(
        "--venv-dir",
        type=str,
        default=VENV_TEMPLATE_PATH,
        help=f"Output directory for Python venv template (default: {VENV_TEMPLATE_PATH})",
    )
    parser.add_argument(
        "--requirements",
        type=str,
        default=None,
        help="Path to requirements.txt (default: auto-detect)",
    )

    args = parser.parse_args()

    venv_dir = Path(args.venv_dir)

    # Find requirements file
    if args.requirements:
        requirements_file = Path(args.requirements)
    else:
        # Try to find requirements file relative to script location
        script_dir = Path(__file__).parent
        requirements_file = (
            script_dir.parent.parent
            / "sandbox"
            / "kubernetes"
            / "docker"
            / "initial-requirements.txt"
        )
        if not requirements_file.exists():
            raise FileNotFoundError(
                "Could not find requirements file. "
                f"Expected at {requirements_file} or specify with --requirements"
            )

    # Show web template location
    print(f"\nOutputs template path: {OUTPUTS_TEMPLATE_PATH}")
    print(f"Venv template path: {VENV_TEMPLATE_PATH}")

    # Build Python venv template
    print(f"\nBuilding Python venv template to {venv_dir}...")
    print("  (This may take 30-60 seconds)")
    build_python_venv_template(venv_dir, requirements_file)
    print("✅ Python venv template built successfully")

    print("\nTemplate ready! You can now create sandboxes.")


if __name__ == "__main__":
    main()
