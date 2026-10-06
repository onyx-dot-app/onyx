import io
from uuid import UUID

import httpx

from onyx.connectors.edit_plan.models import EditPlanChoices
from onyx.db.enums import AccessType
from onyx.server.documents.connector_edit_models import (
    ConnectorEditApplyResponse,
    ConnectorEditPlanResponse,
    ConnectorEditProposal,
)
from onyx.server.documents.models import FileUploadResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.test_models import DATestUser


def _edit_url(cc_pair_id: int, path: str) -> str:
    return f"{API_SERVER_URL}/manage/admin/cc-pair/{cc_pair_id}/edit/{path}"


class ConnectorEditManager:
    """The plan -> confirm -> apply flow of a cc-pair edit. The ``*_response``
    methods return the raw response, so a test can assert a rejection."""

    @staticmethod
    def current_proposal(
        cc_pair_id: int, user_performing_action: DATestUser
    ) -> ConnectorEditProposal:
        """The pair's current state, as a proposal to change."""
        info = CCPairManager.get_single(cc_pair_id, user_performing_action)
        if info is None:
            raise ValueError(f"cc_pair {cc_pair_id} not found")
        data_access_group_ids = (
            sorted(
                CCPairManager.get_data_access_group_ids(
                    cc_pair_id, user_performing_action
                )
            )
            if info.access_type in AccessType.data_access_types()
            else []
        )
        return ConnectorEditProposal(
            connector_specific_config=info.connector.connector_specific_config,
            access_type=info.access_type,
            data_access_group_ids=data_access_group_ids,
            credential_id=info.credential.id,
            indexing_start=info.connector.indexing_start,
            name=info.name,
            refresh_freq=info.connector.refresh_freq,
            prune_freq=info.connector.prune_freq,
        )

    @staticmethod
    def plan_response(
        cc_pair_id: int,
        proposal: ConnectorEditProposal,
        user_performing_action: DATestUser,
    ) -> httpx.Response:
        return client.post(
            _edit_url(cc_pair_id, "plan"),
            json=proposal.model_dump(mode="json"),
            headers=user_performing_action.headers,
        )

    @staticmethod
    def plan(
        cc_pair_id: int,
        proposal: ConnectorEditProposal,
        user_performing_action: DATestUser,
    ) -> ConnectorEditPlanResponse:
        response = ConnectorEditManager.plan_response(
            cc_pair_id, proposal, user_performing_action
        )
        response.raise_for_status()
        return ConnectorEditPlanResponse.model_validate(response.json())

    @staticmethod
    def get_plan_response(
        cc_pair_id: int, plan_id: UUID, user_performing_action: DATestUser
    ) -> httpx.Response:
        return client.get(
            _edit_url(cc_pair_id, f"plan/{plan_id}"),
            headers=user_performing_action.headers,
        )

    @staticmethod
    def apply_response(
        cc_pair_id: int,
        plan_id: UUID,
        user_performing_action: DATestUser,
        choices: EditPlanChoices | None = None,
    ) -> httpx.Response:
        body = (choices or EditPlanChoices()).model_dump(mode="json")
        body["plan_id"] = str(plan_id)
        return client.post(
            _edit_url(cc_pair_id, "apply"),
            json=body,
            headers=user_performing_action.headers,
        )

    @staticmethod
    def apply(
        cc_pair_id: int,
        plan_id: UUID,
        user_performing_action: DATestUser,
        choices: EditPlanChoices | None = None,
    ) -> ConnectorEditApplyResponse:
        response = ConnectorEditManager.apply_response(
            cc_pair_id, plan_id, user_performing_action, choices
        )
        response.raise_for_status()
        return ConnectorEditApplyResponse.model_validate(response.json())

    @staticmethod
    def plan_and_apply(
        cc_pair_id: int,
        proposal: ConnectorEditProposal,
        user_performing_action: DATestUser,
        choices: EditPlanChoices | None = None,
    ) -> ConnectorEditApplyResponse:
        plan = ConnectorEditManager.plan(cc_pair_id, proposal, user_performing_action)
        return ConnectorEditManager.apply(
            cc_pair_id, plan.plan_id, user_performing_action, choices
        )

    @staticmethod
    def stage_files(
        cc_pair_id: int,
        files: list[tuple[str, bytes]],
        user_performing_action: DATestUser,
        draft_zip_metadata_file_id: str | None = None,
    ) -> FileUploadResponse:
        headers = user_performing_action.headers.copy()
        headers.pop("Content-Type", None)
        response = client.post(
            _edit_url(cc_pair_id, "files"),
            files=[
                ("files", (name, io.BytesIO(content), "text/plain"))
                for name, content in files
            ],
            data=(
                {"draft_zip_metadata_file_id": draft_zip_metadata_file_id}
                if draft_zip_metadata_file_id is not None
                else None
            ),
            headers=headers,
        )
        response.raise_for_status()
        return FileUploadResponse.model_validate(response.json())
