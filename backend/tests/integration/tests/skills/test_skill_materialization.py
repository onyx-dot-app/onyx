"""Integration coverage for per-session skill materialization.

Boots a sandbox session and asserts that the per-session `.agents/skills/`
symlink farm + `.skills_manifest.json` are produced according to the
built-in skill registry contract.
"""

import json
from pathlib import Path

import pytest


@pytest.mark.skip(
    reason="TODO(P3.101): wire to integration sandbox fixture once a "
    "BuildSessionManager helper exists in common_utils."
)
def test_pptx_skill_materializes_in_session(tmp_path: Path) -> None:
    """Asserts post-session-setup state:

    1. `.agents/skills/pptx/SKILL.md` is reachable via symlink.
    2. `.agents/skills/.skills_manifest.json` lists `pptx` as a built-in entry.
    3. `.agents/skills/company-search` is absent (templated, skipped in P3).

    Wire-up notes for whoever picks this up:
    - Create a build session via the project's API (mirror
      ``backend/tests/integration/tests/streaming_endpoints/test_chat_stream.py``).
    - Trigger ``setup_session_workspace`` (happens implicitly on first
      session start in local-sandbox mode).
    - In local mode, the session dir lives under ``SANDBOX_BASE_PATH``;
      resolve it via ``LocalSandboxManager._get_session_path``.
    """
    session_path = tmp_path  # placeholder

    skills_root = session_path / ".agents" / "skills"
    assert (skills_root / "pptx" / "SKILL.md").exists()

    manifest = json.loads((skills_root / ".skills_manifest.json").read_text())
    builtin_slugs = {entry["slug"] for entry in manifest["builtin"]}
    assert "pptx" in builtin_slugs
    assert "company-search" not in builtin_slugs

    assert not (skills_root / "company-search").exists()
