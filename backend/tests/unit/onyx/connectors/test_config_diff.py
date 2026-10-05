from typing import Annotated, Any, Self

import pytest

from onyx.connectors.config_diff import (
    ConfigFieldChange,
    build_field_policy_report,
    build_scoped_backfill_config,
    classify_config_change,
    find_field_policy_gaps,
)
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeExclude,
    ScopeInclude,
    ScopeOpaque,
    ScopeToggle,
)
from onyx.connectors.github.config import GithubConnectorConfig
from onyx.connectors.slack.config import SlackConnectorConfig


class _Config(ConnectorConfig):
    owner: Annotated[str, FieldPolicy(FieldClass.IDENTITY)] = "owner"
    spaces: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("regex_mode",),
        ),
    ] = None
    repos: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ] = None
    # None (or a blank string) fetches every kind, [] fetches none.
    kinds: Annotated[
        str | list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True, empty_list_means_none=True),
        ),
    ] = None
    skipped: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    include_archived: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=True))
    ] = False
    skip_drafts: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=False))
    ] = True
    query: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = ""
    regex_mode: Annotated[bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = (
        False
    )
    parse_tables: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = 10
    unclassified: int = 0


class _HookConfig(_Config):
    @classmethod
    def classify_scope_change(  # ty: ignore[invalid-method-override]
        cls, old: Self, new: Self
    ) -> dict[str, ScopeDirection]:
        if old.query == "a" and new.query == "a OR b":
            return {"query": ScopeDirection.WIDEN}
        return {}


class _BadHookConfig(_Config):
    @classmethod
    def classify_scope_change(  # ty: ignore[invalid-method-override]
        cls,
        old: Self,  # noqa: ARG003
        new: Self,  # noqa: ARG003
    ) -> dict[str, ScopeDirection]:
        return {"parse_tables": ScopeDirection.WIDEN}


def _only_change(
    old: dict[str, Any],
    new: dict[str, Any],
    config_class: type[ConnectorConfig] = _Config,
) -> ConfigFieldChange:
    changes = classify_config_change(config_class, old, new)
    assert len(changes) == 1, changes
    return changes[0]


@pytest.mark.parametrize(
    "old, new, direction, added, removed",
    [
        (["a"], ["a", "b"], ScopeDirection.WIDEN, ["b"], []),
        (["a", "b"], ["a"], ScopeDirection.NARROW, [], ["b"]),
        (["a"], ["b"], ScopeDirection.BOTH, ["b"], ["a"]),
        # empty_means_all
        (None, ["a"], ScopeDirection.NARROW, ["a"], []),
        ([], ["a"], ScopeDirection.NARROW, ["a"], []),
        (["a"], None, ScopeDirection.WIDEN, [], ["a"]),
        (["a"], [], ScopeDirection.WIDEN, [], ["a"]),
        # List entries are matched exactly, so whitespace is a change.
        (["general "], ["general"], ScopeDirection.BOTH, ["general"], ["general "]),
    ],
)
def test_include_directions(
    old: list[str] | None,
    new: list[str] | None,
    direction: ScopeDirection,
    added: list[str],
    removed: list[str],
) -> None:
    change = _only_change({"spaces": old}, {"spaces": new})

    assert change.field_class == FieldClass.SCOPE
    assert change.scope_direction == direction
    assert change.added_items == added
    assert change.removed_items == removed


@pytest.mark.parametrize(
    "old, new, direction",
    [
        ("a", "a, b", ScopeDirection.WIDEN),
        ("a,b", "a", ScopeDirection.NARROW),
        # Without empty_means_all, empty fetches nothing.
        (None, "a", ScopeDirection.WIDEN),
        ("a", "", ScopeDirection.NARROW),
    ],
)
def test_include_comma_separated_string(
    old: str | None, new: str, direction: ScopeDirection
) -> None:
    assert _only_change({"repos": old}, {"repos": new}).scope_direction == direction


@pytest.mark.parametrize(
    "old, new, direction",
    [
        # Only None (or a blank string) means all.
        (None, [], ScopeDirection.NARROW),
        (None, ["a"], ScopeDirection.NARROW),
        ("", "a", ScopeDirection.NARROW),
        ([], None, ScopeDirection.WIDEN),
        (["a"], None, ScopeDirection.WIDEN),
        # [] fetches nothing.
        ([], ["a"], ScopeDirection.WIDEN),
        (["a"], [], ScopeDirection.NARROW),
        (["a"], ["a", "b"], ScopeDirection.WIDEN),
    ],
)
def test_include_where_only_none_means_all(
    old: str | list[str] | None,
    new: str | list[str] | None,
    direction: ScopeDirection,
) -> None:
    assert _only_change({"kinds": old}, {"kinds": new}).scope_direction == direction


def test_include_where_only_none_means_all_scoped_backfill() -> None:
    assert build_scoped_backfill_config(_Config, {"kinds": []}, {"kinds": ["a"]}) == {
        "kinds": ["a"]
    }
    assert (
        build_scoped_backfill_config(_Config, {"kinds": ["a"]}, {"kinds": None}) is None
    )


def test_empty_list_means_none_needs_empty_means_all() -> None:
    with pytest.raises(ValueError):
        ScopeInclude(empty_means_all=False, empty_list_means_none=True)


def test_include_change_without_scope_effect_is_left_out() -> None:
    assert classify_config_change(_Config, {"repos": "a,b"}, {"repos": " b , a,"}) == []
    assert classify_config_change(_Config, {"spaces": None}, {"spaces": []}) == []


@pytest.mark.parametrize(
    "old, new, direction",
    [
        (["a"], ["a", "b"], ScopeDirection.NARROW),
        (["a", "b"], ["a"], ScopeDirection.WIDEN),
        (None, ["a"], ScopeDirection.NARROW),
        (["a"], ["b"], ScopeDirection.BOTH),
    ],
)
def test_exclude_directions(
    old: list[str] | None, new: list[str], direction: ScopeDirection
) -> None:
    assert _only_change({"skipped": old}, {"skipped": new}).scope_direction == direction


@pytest.mark.parametrize(
    "field_name, old, new, direction",
    [
        ("include_archived", False, True, ScopeDirection.WIDEN),
        ("include_archived", True, False, ScopeDirection.NARROW),
        ("skip_drafts", True, False, ScopeDirection.WIDEN),
        ("skip_drafts", False, True, ScopeDirection.NARROW),
    ],
)
def test_toggle_directions(
    field_name: str, old: bool, new: bool, direction: ScopeDirection
) -> None:
    change = _only_change({field_name: old}, {field_name: new})

    assert change.scope_direction == direction


def test_opaque_is_unknown() -> None:
    assert (
        _only_change({"query": "a"}, {"query": "b"}).scope_direction
        == ScopeDirection.UNKNOWN
    )


def test_changed_dependency_makes_change_unknown() -> None:
    changes = classify_config_change(
        _Config,
        {"spaces": ["a"]},
        {"spaces": ["a", "b"], "regex_mode": True},
    )

    assert {change.field_name: change.scope_direction for change in changes} == {
        "spaces": ScopeDirection.UNKNOWN,
        "regex_mode": ScopeDirection.UNKNOWN,
    }


def test_unchanged_dependency_keeps_direction() -> None:
    change = _only_change(
        {"spaces": ["a"], "regex_mode": True},
        {"spaces": ["a", "b"], "regex_mode": True},
    )

    assert change.scope_direction == ScopeDirection.WIDEN


def test_non_scope_classes_and_unclassified_counts_as_behavior() -> None:
    changes = classify_config_change(
        _Config,
        {},
        {"owner": "other", "parse_tables": True, "batch_size": 5, "unclassified": 1},
    )

    assert [(change.field_name, change.field_class) for change in changes] == [
        ("owner", FieldClass.IDENTITY),
        ("parse_tables", FieldClass.BEHAVIOR),
        ("batch_size", FieldClass.COSMETIC),
        ("unclassified", FieldClass.BEHAVIOR),
    ]
    assert all(change.scope_direction == ScopeDirection.NONE for change in changes)


def test_defaults_and_coercion_are_not_changes() -> None:
    assert (
        classify_config_change(
            _Config, {"batch_size": "10"}, {"include_archived": False}
        )
        == []
    )


def test_invalid_config_compares_raw_values() -> None:
    changes = classify_config_change(
        _Config,
        {"spaces": ["a"], "legacy_key": 1},
        {"spaces": ["a", "b"]},
    )

    assert {change.field_name: change.scope_direction for change in changes} == {
        "spaces": ScopeDirection.WIDEN,
        "legacy_key": ScopeDirection.NONE,
    }
    assert changes[1].field_class == FieldClass.BEHAVIOR


def test_hook_overrides_descriptor() -> None:
    assert (
        _only_change({"query": "a"}, {"query": "a OR b"}, _HookConfig).scope_direction
        == ScopeDirection.WIDEN
    )
    assert (
        _only_change({"query": "a"}, {"query": "c"}, _HookConfig).scope_direction
        == ScopeDirection.UNKNOWN
    )


def test_hook_naming_a_non_scope_field_raises() -> None:
    with pytest.raises(ValueError):
        classify_config_change(_BadHookConfig, {}, {"parse_tables": True})


def test_field_policy_rejects_scope_on_non_scope_field() -> None:
    with pytest.raises(ValueError):
        FieldPolicy(FieldClass.BEHAVIOR, scope=ScopeOpaque())


def test_scoped_backfill_keeps_only_added_items() -> None:
    delta = build_scoped_backfill_config(
        _Config,
        {"spaces": ["a"], "repos": "x", "skipped": ["s"], "batch_size": 10},
        {"spaces": ["a"], "repos": "x, y", "skipped": ["s"], "batch_size": 20},
    )

    assert delta == {
        "spaces": ["a"],
        "repos": "y",
        "skipped": ["s"],
        "batch_size": 20,
    }


def test_scoped_backfill_is_none_when_two_include_fields_widen() -> None:
    # A document must match both fields: the added items alone would miss
    # (a, y) and (b, x).
    assert (
        build_scoped_backfill_config(
            _Config,
            {"spaces": ["a"], "repos": "x"},
            {"spaces": ["a", "b"], "repos": "x, y"},
        )
        is None
    )


@pytest.mark.parametrize(
    "old, new",
    [
        # No change, or only a cosmetic change.
        ({}, {}),
        ({}, {"batch_size": 20}),
        # Narrowing or both.
        ({"spaces": ["a", "b"]}, {"spaces": ["a"]}),
        ({"spaces": ["a"]}, {"spaces": ["b"]}),
        # empty_means_all: widening to everything has no delta.
        ({"spaces": ["a"]}, {"spaces": None}),
        # A widening that is not a ScopeInclude field.
        ({"skipped": ["s"]}, {"skipped": None}),
        ({}, {"include_archived": True}),
        # Opaque, or a changed dependency.
        ({"query": "a"}, {"query": "b"}),
        ({"spaces": ["a"]}, {"spaces": ["a", "b"], "regex_mode": True}),
        # Identity or behavior next to a widening.
        ({"spaces": ["a"]}, {"spaces": ["a", "b"], "owner": "other"}),
        ({"spaces": ["a"]}, {"spaces": ["a", "b"], "parse_tables": True}),
        ({"spaces": ["a"]}, {"spaces": ["a", "b"], "unclassified": 1}),
    ],
)
def test_scoped_backfill_is_none(old: dict[str, Any], new: dict[str, Any]) -> None:
    assert build_scoped_backfill_config(_Config, old, new) is None


def test_slack_regex_mode_change_is_unknown() -> None:
    changes = classify_config_change(
        SlackConnectorConfig,
        {"channels": ["general"]},
        {"channels": ["gen.*"], "channel_regex_enabled": True},
    )

    assert {change.field_name: change.scope_direction for change in changes} == {
        "channels": ScopeDirection.UNKNOWN,
        "channel_regex_enabled": ScopeDirection.UNKNOWN,
    }


@pytest.mark.parametrize(
    "old, new, direction",
    [
        (False, True, ScopeDirection.WIDEN),
        (True, False, ScopeDirection.BOTH),
    ],
)
def test_slack_bot_messages(old: bool, new: bool, direction: ScopeDirection) -> None:
    change = _only_change(
        {"include_bot_messages": old},
        {"include_bot_messages": new},
        SlackConnectorConfig,
    )

    assert change.scope_direction == direction


@pytest.mark.parametrize(
    "raw, expected",
    [(None, None), ("", None), ("  ", None), (" main ", "main")],
)
def test_github_branch_and_repositories_are_stripped(
    raw: str | None, expected: str | None
) -> None:
    config = GithubConnectorConfig.model_validate(
        {"repo_owner": "onyx", "repositories": raw, "branch": raw}
    )

    assert config.repositories == expected
    assert config.branch == expected


def test_github_whitespace_is_not_a_change() -> None:
    assert (
        classify_config_change(
            GithubConnectorConfig,
            {"repo_owner": "onyx", "repositories": "a", "branch": "main"},
            {"repo_owner": "onyx", "repositories": " a ", "branch": " main "},
        )
        == []
    )


def test_github_scoped_backfill_for_added_repositories() -> None:
    delta = build_scoped_backfill_config(
        GithubConnectorConfig,
        {"repo_owner": "onyx", "repositories": "a", "include_issues": True},
        {"repo_owner": "onyx", "repositories": "a,b", "include_issues": True},
    )

    assert delta == {"repo_owner": "onyx", "repositories": "b", "include_issues": True}


class _GapConfig(ConnectorConfig):
    classified: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = 0
    no_descriptor: Annotated[str, FieldPolicy(FieldClass.SCOPE)] = ""
    no_policy: int = 0


def test_find_field_policy_gaps() -> None:
    gaps = find_field_policy_gaps(_GapConfig)

    assert gaps.fields_without_policy == ["no_policy"]
    assert gaps.scope_fields_without_descriptor == ["no_descriptor"]


def test_every_source_has_complete_policies() -> None:
    # A new config field needs a FieldPolicy, and a SCOPE field a descriptor.
    assert build_field_policy_report() == {}


class _PathConfig(ConnectorConfig):
    folder_path: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=False, split_on_commas=False),
        ),
    ] = None


def test_one_item_string_is_not_split_on_commas() -> None:
    changes = classify_config_change(
        _PathConfig, {"folder_path": "/a"}, {"folder_path": "/Q1, 2024"}
    )

    assert len(changes) == 1
    assert changes[0].scope_direction == ScopeDirection.BOTH
    assert changes[0].added_items == ["/Q1, 2024"]
    assert changes[0].removed_items == ["/a"]


def test_one_item_string_backfill_keeps_the_exact_value() -> None:
    delta = build_scoped_backfill_config(
        _PathConfig, {"folder_path": None}, {"folder_path": " /Q1, 2024"}
    )

    assert delta == {"folder_path": " /Q1, 2024"}
