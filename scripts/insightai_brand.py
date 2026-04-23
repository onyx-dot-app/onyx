"""Seed Onyx EE enterprise settings with the InsightAI brand.

Runs idempotently. Writes to the KV store (application name + custom logo flags)
and uploads the logo + logotype PNGs into the file store. After this runs,
the app chrome (title, favicon, login, sidebar, emails) shows InsightAI
without further source-code changes.

Usage (from repo root, with backend venv active and infra up):

    source .venv/bin/activate
    python scripts/insightai_brand.py

Override logo paths if needed:

    python scripts/insightai_brand.py \
        --logo backend/static/images/logo.png \
        --logotype backend/static/images/logotype.png \
        --name InsightAI
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
DEFAULT_LOGO = BACKEND / "static" / "images" / "logo.png"
DEFAULT_LOGOTYPE = BACKEND / "static" / "images" / "logotype.png"


def _bootstrap_path() -> None:
    """Make `ee.*` and `onyx.*` importable when run from repo root."""
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)


def seed(name: str, logo: Path, logotype: Path) -> None:
    _bootstrap_path()

    from ee.onyx.server.enterprise_settings.models import EnterpriseSettings
    from ee.onyx.server.enterprise_settings.store import (
        load_settings,
        store_settings,
        upload_logo,
    )

    current = load_settings()

    merged = EnterpriseSettings(
        **{
            **current.model_dump(),
            "application_name": name,
            "use_custom_logo": True,
            "use_custom_logotype": True,
        }
    )
    store_settings(merged)
    print(f"[ok] enterprise_settings.application_name = {name!r}")
    print(f"[ok] use_custom_logo = True, use_custom_logotype = True")

    if not logo.is_file():
        raise SystemExit(f"[err] logo not found: {logo}")
    if not logotype.is_file():
        raise SystemExit(f"[err] logotype not found: {logotype}")

    if not upload_logo(str(logo), is_logotype=False):
        raise SystemExit(f"[err] failed to upload logo {logo}")
    print(f"[ok] uploaded logo  <- {logo}")

    if not upload_logo(str(logotype), is_logotype=True):
        raise SystemExit(f"[err] failed to upload logotype {logotype}")
    print(f"[ok] uploaded logotype  <- {logotype}")

    print("\n[done] InsightAI brand seeded. Hard-refresh the browser to pick up changes.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="InsightAI", help="application_name to seed")
    parser.add_argument(
        "--logo",
        type=Path,
        default=DEFAULT_LOGO,
        help="Path to square logo PNG (>=512x512)",
    )
    parser.add_argument(
        "--logotype",
        type=Path,
        default=DEFAULT_LOGOTYPE,
        help="Path to horizontal logotype PNG (~1024x256)",
    )
    args = parser.parse_args()

    seed(name=args.name, logo=args.logo.resolve(), logotype=args.logotype.resolve())


if __name__ == "__main__":
    main()
