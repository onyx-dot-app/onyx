from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.draft_runs import DraftCheckStateKind
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.server.documents.capability_check_runs import plan_draft_capability_checks


def _states(source: DocumentSource) -> dict[str, DraftCheckStateKind]:
    plan = plan_draft_capability_checks(
        source=source,
        config_class=CONNECTOR_CLASS_MAP[source].config_class,
        access_type=None,
        form_values={},
    )
    return {check.check_id: check.state for check in plan.checks}


def test_an_empty_form_runs_checks_when_the_defaults_are_complete() -> None:
    # Every Linear config field has a default, so the form never sends values.
    states = _states(DocumentSource.LINEAR)
    assert states["linear_token"] == DraftCheckStateKind.PENDING
    assert states["linear_issues"] == DraftCheckStateKind.PENDING
    # An empty scope list means every team and project, so there is nothing to check.
    assert states["linear_teams"] == DraftCheckStateKind.NOT_APPLICABLE
    assert states["linear_projects"] == DraftCheckStateKind.NOT_APPLICABLE


def test_an_empty_form_waits_when_a_field_is_required() -> None:
    # workspace has no default.
    assert _states(DocumentSource.BITBUCKET) == {
        "bitbucket_connector_settings": DraftCheckStateKind.WAITING
    }


def test_an_empty_form_runs_only_the_named_checks_that_need_no_field() -> None:
    # The GitHub sign-in needs no config; the other checks need repo_owner.
    states = _states(DocumentSource.GITHUB)

    assert states["github_auth"] == DraftCheckStateKind.PENDING
    assert states["github_token_scopes"] == DraftCheckStateKind.PENDING
    assert states["github_owner"] == DraftCheckStateKind.WAITING
    assert states["github_pull_requests"] == DraftCheckStateKind.WAITING
