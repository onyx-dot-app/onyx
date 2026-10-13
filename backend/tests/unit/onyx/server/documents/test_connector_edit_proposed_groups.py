"""A proposal without data-access groups keeps the pair's groups. An editor
may see only some of them, so the edit form sends none when the access did
not change."""

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.edit_plan.models import CurrentPairState, ProposedPairState
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.server.documents.connector_edit import _proposed_state
from onyx.server.documents.connector_edit_models import ConnectorEditProposal

_CURRENT = CurrentPairState(
    cc_pair_id=1,
    connector_id=1,
    status=ConnectorCredentialPairStatus.ACTIVE,
    source=DocumentSource.GITHUB,
    input_type=InputType.POLL,
    connector_specific_config={"repo_owner": "onyx-dot-app"},
    access_type=AccessType.PRIVATE,
    data_access_group_ids=[2, 5],
    credential_id=7,
    name="Docs repos",
)


def _proposal(data_access_group_ids: list[int] | None) -> ConnectorEditProposal:
    return ConnectorEditProposal(
        connector_specific_config={"repo_owner": "onyx-dot-app"},
        access_type=AccessType.PRIVATE,
        data_access_group_ids=data_access_group_ids,
        credential_id=7,
        name="Docs repos",
    )


@pytest.mark.parametrize(
    ("proposed_ids", "expected_ids"),
    [(None, [2, 5]), ([5], [5]), ([], [])],
)
def test_proposed_groups(
    proposed_ids: list[int] | None, expected_ids: list[int]
) -> None:
    proposed: ProposedPairState = _proposed_state(_CURRENT, _proposal(proposed_ids))

    assert proposed.data_access_group_ids == expected_ids


def test_a_request_without_groups_keeps_them() -> None:
    proposal = ConnectorEditProposal.model_validate(
        {
            "connector_specific_config": {},
            "access_type": "private",
            "credential_id": 7,
            "name": "Docs repos",
        }
    )

    assert _proposed_state(_CURRENT, proposal).data_access_group_ids == [2, 5]
