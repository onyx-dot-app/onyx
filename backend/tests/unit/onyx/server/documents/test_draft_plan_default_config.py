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
    assert _states(DocumentSource.LINEAR) == {
        "linear_connector_settings": DraftCheckStateKind.PENDING
    }


def test_an_empty_form_waits_when_a_field_is_required() -> None:
    # repo_owner has no default.
    assert _states(DocumentSource.GITHUB) == {
        "github_connector_settings": DraftCheckStateKind.WAITING
    }
