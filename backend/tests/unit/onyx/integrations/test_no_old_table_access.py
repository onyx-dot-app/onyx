"""Production code reads and writes sign-in, policy and access data only in
the integration tables. This test fails when code uses a model of an old
table again."""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4]
SCANNED = [BACKEND / "onyx", BACKEND / "ee"]
OLD_MODELS = re.compile(
    r"\b(MCPConnectionConfig|OAuthConfig|OAuthUserToken|ExternalAppUserCredential"
    r"|WorkspaceActionPolicy|UserActionPolicy|ScheduledTaskEnabledApp"
    r"|ScheduledTaskActionPolicy|MCPServerUserPreference|ToolUserPreference"
    r"|MCPServer__User|MCPServer__UserGroup|GatedApp)\b"
)
# Each allowed file, with the reason it may use an old model.
ALLOWED_FILES = {
    # The model definitions.
    BACKEND / "onyx" / "db" / "models.py": "definitions",
    # An approval row keeps the gated_app id of its integration, which the
    # previous release reads after a rollback.
    BACKEND / "onyx" / "db" / "approval_request.py": "rollback key",
    # An email change keeps the old MCP rows bound to the user, which the
    # previous release reads after a rollback.
    BACKEND / "onyx" / "db" / "users.py": "rollback rows",
    # A group delete removes the group's MCP server rows: their foreign key
    # has no cascade.
    BACKEND / "ee" / "onyx" / "db" / "user_group.py": "group delete",
    # The community downgrade makes the servers of the removed groups public.
    BACKEND / "ee" / "onyx" / "db" / "community_downgrade.py": "downgrade",
}


def test_no_production_code_uses_an_old_table() -> None:
    hits: list[str] = []
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
            if path in ALLOWED_FILES:
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if not line.lstrip().startswith("#") and OLD_MODELS.search(line):
                    hits.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
    assert hits == []


def test_each_allowed_file_still_uses_an_old_table() -> None:
    """An allowed file that no longer needs its exception loses it."""
    assert [
        str(path.relative_to(BACKEND))
        for path in ALLOWED_FILES
        if not OLD_MODELS.search(path.read_text())
    ] == []
