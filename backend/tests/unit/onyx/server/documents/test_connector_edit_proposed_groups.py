"""The data-access groups of an edit proposal. A proposal without groups keeps
the pair's groups. An editor who sees only some groups cannot see, add or
remove the others."""

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.edit_plan.models import CurrentPairState, ProposedPairState
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.connector_edit import _proposed_state
from onyx.server.documents.connector_edit_models import ConnectorEditProposal

# Group 2 is visible to the scoped editor; group 5 is not.
_VISIBLE = {2, 3}
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
    ("proposed_ids", "visible_ids", "expected_ids"),
    [
        # None keeps the pair's groups, for anyone.
        (None, _VISIBLE, [2, 5]),
        (None, None, [2, 5]),
        # A scoped editor's list touches only the groups it can see.
        ([2], _VISIBLE, [2, 5]),
        ([], _VISIBLE, [5]),
        ([2, 3], _VISIBLE, [2, 3, 5]),
        # An editor who sees every group sets the list as sent.
        ([5], None, [5]),
        ([], None, []),
    ],
)
def test_proposed_groups(
    proposed_ids: list[int] | None,
    visible_ids: set[int] | None,
    expected_ids: list[int],
) -> None:
    proposed: ProposedPairState = _proposed_state(
        _CURRENT, _proposal(proposed_ids), visible_ids
    )

    assert proposed.data_access_group_ids == expected_ids


def test_a_scoped_editor_cannot_add_a_group_it_cannot_see() -> None:
    with pytest.raises(OnyxError):
        _proposed_state(_CURRENT, _proposal([2, 9]), _VISIBLE)


def test_a_request_without_groups_keeps_them() -> None:
    proposal = ConnectorEditProposal.model_validate(
        {
            "connector_specific_config": {},
            "access_type": "private",
            "credential_id": 7,
            "name": "Docs repos",
        }
    )

    assert _proposed_state(_CURRENT, proposal, _VISIBLE).data_access_group_ids == [
        2,
        5,
    ]
