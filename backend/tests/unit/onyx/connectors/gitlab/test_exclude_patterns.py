from onyx.connectors.gitlab.connector import (
    DEFAULT_EXCLUDE_PATTERNS,
    GitlabConnector,
    _should_exclude,
)


def test_default_exclude_patterns_preserved_when_not_overridden():
    connector = GitlabConnector(project_owner="onyx-dot-app", project_name="onyx")
    assert connector.exclude_patterns == DEFAULT_EXCLUDE_PATTERNS


def test_custom_exclude_patterns_are_additive_not_replacing():
    connector = GitlabConnector(
        project_owner="onyx-dot-app",
        project_name="onyx",
        exclude_patterns=["package-lock.json", "*.lock"],
    )
    for pattern in DEFAULT_EXCLUDE_PATTERNS:
        assert pattern in connector.exclude_patterns
    assert "package-lock.json" in connector.exclude_patterns
    assert "*.lock" in connector.exclude_patterns


def test_should_exclude_matches_custom_pattern():
    patterns = DEFAULT_EXCLUDE_PATTERNS + ["*.lock"]
    assert _should_exclude("yarn.lock", patterns) is True
    assert _should_exclude("src/main.py", patterns) is False
