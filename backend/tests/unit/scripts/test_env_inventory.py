"""Unit tests for the env-var inventory tool's classifier and AST extraction.

The classifier drives an actionable "should be documented" shortlist, so its
heuristics are worth locking down — a wrong tag silently hides a var (or
mislabels a secret).
"""

import ast
from pathlib import Path

import pytest
from scripts.env_inventory import classify_var
from scripts.env_inventory import diff_baseline
from scripts.env_inventory import EnvVisitor
from scripts.env_inventory import format_baseline
from scripts.env_inventory import is_sensitive
from scripts.env_inventory import read_baseline


@pytest.mark.parametrize(
    "name",
    [
        "USER_AUTH_SECRET",
        "REDIS_PASSWORD",
        "POSTGRES_PASSWORD",
        "PDF_PASSWORD",
        "OPENAI_DEFAULT_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "STRIPE_SECRET_KEY",
        "ACCESS_TOKEN_GITHUB",
        "SLACK_BOT_TOKEN",
        "GCS_SERVICE_ACCOUNT_KEY_JSON",
        "ENCRYPTION_KEY_SECRET",
        "VERTEXAI_DEFAULT_CREDENTIALS",
    ],
)
def test_is_sensitive_true(name: str) -> None:
    assert is_sensitive(name) is True


@pytest.mark.parametrize(
    "name",
    [
        # token / key *counts* and policy, not credentials
        "AGENT_MAX_TOKENS_VALIDATION",
        "GEN_AI_INPUT_TOKEN_SAFETY_MARGIN",
        "PASSWORD_MIN_LENGTH",
        "PASSWORD_REQUIRE_DIGIT",
        # public material is not a secret
        "STRIPE_PUBLISHABLE_KEY",
        "RECAPTCHA_SITE_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LICENSE_PUBLIC_KEY_PEM",
        "JWT_PUBLIC_KEY_URL",
        # references AT a secret (path/id/username), not the secret itself
        "AWS_ACCESS_KEY_ID",
        "POSTGRES_SSLKEY",
        "REDIS_SSL_KEYFILE",
        "DISCOURSE_API_USERNAME",
    ],
)
def test_is_sensitive_false(name: str) -> None:
    assert is_sensitive(name) is False


def test_classify_category_axis() -> None:
    # platform-injected
    assert classify_var("HOSTNAME", set())[0] == "platform"
    assert classify_var("KUBERNETES_SERVICE_HOST", set())[0] == "platform"
    # read under connectors/ -> connector, regardless of name shape
    assert (
        classify_var(
            "CONFLUENCE_ACCESS_TOKEN", {"backend/onyx/connectors/confluence/c.py"}
        )[0]
        == "connector"
    )
    # dev/test/eval -> internal (high precision)
    assert classify_var("DEV_MODE", set())[0] == "internal"
    assert classify_var("MOCK_LLM_RESPONSE", set())[0] == "internal"
    assert classify_var("ONYX_EVAL_API_KEY", set())[0] == "internal"
    # operator-facing knob -> tunable
    assert classify_var("AGENT_MAX_QUERY_RETRIEVAL_RESULTS", set())[0] == "tunable"


def test_classify_retrieval_not_misread_as_eval() -> None:
    # "RETRIEVAL" contains the substring "EVAL" — must not be tagged internal.
    cat, _ = classify_var("AGENT_MAX_QUERY_RETRIEVAL_RESULTS", set())
    assert cat == "tunable"


def test_classify_sensitive_orthogonal_to_category() -> None:
    # a connector credential is both connector AND sensitive
    cat, sensitive = classify_var(
        "JIRA_API_TOKEN", {"backend/onyx/connectors/jira/connector.py"}
    )
    assert cat == "connector"
    assert sensitive is True


def _names(src: str) -> set[str]:
    from scripts.env_inventory import _scan_os_imports

    tree = ast.parse(src)
    environ_aliases, getenv_aliases = _scan_os_imports(tree)
    visitor = EnvVisitor("backend/onyx/x.py", False, environ_aliases, getenv_aliases)
    visitor.visit(tree)
    return {r.name for r in visitor.reads}


def test_visitor_catches_dotted_and_bare_os_reads() -> None:
    src = (
        "import os\n"
        "from os import environ, getenv\n"
        "from os import environ as ENV\n"
        'A = os.environ.get("DOTTED_GET")\n'
        'B = os.getenv("DOTTED_GETENV")\n'
        'C = os.environ["DOTTED_SUB"]\n'
        'D = environ.get("BARE_GET")\n'
        'E = getenv("BARE_GETENV")\n'
        'F = environ["BARE_SUB"]\n'
        'G = ENV.get("ALIASED")\n'
    )
    assert _names(src) == {
        "DOTTED_GET",
        "DOTTED_GETENV",
        "DOTTED_SUB",
        "BARE_GET",
        "BARE_GETENV",
        "BARE_SUB",
        "ALIASED",
    }


def test_visitor_ignores_non_uppercase_and_non_literal_keys() -> None:
    src = (
        "import os\n"
        'a = os.environ.get("lowercase_ignored")\n'
        "b = os.environ.get(some_variable)\n"
    )
    assert _names(src) == set()


# --- drift baseline (CI gate) -------------------------------------------------


def test_baseline_roundtrip_ignores_comments_and_blanks(tmp_path: Path) -> None:
    names = ["ZULIP_KEY", "ALPHA_FLAG", "ALPHA_FLAG"]  # unsorted + duplicate
    path = tmp_path / "baseline.txt"
    path.write_text(format_baseline(names), encoding="utf-8")
    body = path.read_text(encoding="utf-8")
    # rendered header is comment-only; names are sorted + de-duplicated
    assert body.startswith("#")
    assert "\nALPHA_FLAG\nZULIP_KEY\n" in body
    # read back drops the header comments and blank lines
    assert read_baseline(path) == {"ALPHA_FLAG", "ZULIP_KEY"}


def test_read_baseline_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_baseline(tmp_path / "nope.txt") == set()


def test_diff_baseline_clean_when_equal() -> None:
    current = {"A", "B", "C"}
    assert diff_baseline(current, set(current)) == ([], [])


def test_diff_baseline_flags_new_drift() -> None:
    # code reads NEW that the baseline doesn't list -> gate should fail on it
    new_drift, resolved = diff_baseline({"A", "B", "NEW"}, {"A", "B"})
    assert new_drift == ["NEW"]
    assert resolved == []


def test_diff_baseline_flags_stale_entries() -> None:
    # baseline lists GONE but code no longer leaves it undocumented -> stale
    new_drift, resolved = diff_baseline({"A", "B"}, {"A", "B", "GONE"})
    assert new_drift == []
    assert resolved == ["GONE"]


def test_diff_baseline_reports_both_directions_sorted() -> None:
    new_drift, resolved = diff_baseline({"A", "Y", "X"}, {"A", "C", "B"})
    assert new_drift == ["X", "Y"]
    assert resolved == ["B", "C"]
