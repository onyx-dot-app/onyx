import io
import zipfile
from collections.abc import Sequence
from typing import TypeVar
from uuid import UUID
from uuid import uuid4

import httpx
from pydantic import BaseModel

from onyx.db.enums import SkillSharePermission
from onyx.server.features.skill.models import SkillEditableDetailResponse
from onyx.server.features.skill.models import SkillGroupShareRequest
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.server.features.skill.models import SkillResponse
from onyx.server.features.skill.models import SkillShareRequest
from onyx.server.features.skill.models import SkillsList
from onyx.server.features.skill.models import SkillUserShareRequest
from onyx.server.features.skill.models import TransferSkillOwnershipRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


def _response_model(
    response: httpx.Response,
    model: type[_ResponseModel],
) -> _ResponseModel:
    return model.model_validate(response.json())


def build_minimal_bundle(
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
) -> bytes:
    """Build a minimal valid skill bundle zip with SKILL.md.

    `name` / `description` are written into the bundle's frontmatter — that's
    now the canonical source for those fields on the backend, so tests that
    care about them should pass them here instead of as separate API args.
    """
    fm_name = name or f"Test Skill {slug}"
    fm_desc = description or f"Description for {slug}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            f"---\nname: {fm_name}\ndescription: {fm_desc}\n---\n\nSkill instructions.",
        )
    return buf.getvalue()


class SkillManager:
    @staticmethod
    def create_custom(
        user_performing_action: DATestUser,
        *,
        slug: str | None = None,
        name: str | None = None,
        description: str | None = None,
        is_public: bool = False,
        group_ids: list[int] | None = None,
        bundle_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> SkillResponse:
        slug = slug or f"test-skill-{uuid4().hex[:8]}"
        if bundle_bytes is None:
            bundle_bytes = build_minimal_bundle(
                slug, name=name, description=description
            )

        headers = dict(user_performing_action.headers)
        headers.pop("Content-Type", None)

        response = client.post(
            f"{API_SERVER_URL}/skills/custom",
            files={
                "bundle": (
                    filename or f"{slug}.zip",
                    io.BytesIO(bundle_bytes),
                    "application/zip",
                )
            },
            headers=headers,
        )
        response.raise_for_status()
        skill = _response_model(response, SkillResponse)

        if is_public or group_ids:
            share_req = SkillShareRequest(
                is_public=is_public,
                group_shares=[
                    SkillGroupShareRequest(
                        group_id=group_id,
                        permission=SkillSharePermission.VIEWER,
                    )
                    for group_id in group_ids or []
                ],
            )
            share_response = client.patch(
                f"{API_SERVER_URL}/skills/custom/{skill.id}/share",
                json=share_req.model_dump(mode="json", exclude_none=True),
                headers=user_performing_action.headers,
            )
            share_response.raise_for_status()
            return _response_model(share_response, SkillResponse)

        return skill

    @staticmethod
    def patch_custom(
        skill: SkillResponse,
        user_performing_action: DATestUser,
        patch_req: SkillPatchRequest,
    ) -> SkillResponse:
        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            json=patch_req.model_dump(
                mode="json",
                exclude_unset=True,
            ),
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def replace_bundle(
        skill: SkillResponse,
        bundle_bytes: bytes,
        user_performing_action: DATestUser,
    ) -> SkillResponse:
        headers = dict(user_performing_action.headers)
        headers.pop("Content-Type", None)

        response = client.put(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/bundle",
            files={
                "bundle": (
                    f"{skill.slug}.zip",
                    io.BytesIO(bundle_bytes),
                    "application/zip",
                )
            },
            headers=headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def replace_group_shares(
        skill: SkillResponse,
        group_ids: list[int],
        user_performing_action: DATestUser,
    ) -> SkillResponse:
        share_req = SkillShareRequest(
            group_shares=[
                SkillGroupShareRequest(
                    group_id=group_id,
                    permission=SkillSharePermission.VIEWER,
                )
                for group_id in group_ids
            ],
        )
        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/share",
            json=share_req.model_dump(mode="json", exclude_none=True),
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def delete_custom(
        skill: SkillResponse,
        user_performing_action: DATestUser,
    ) -> None:
        response = client.delete(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

    @staticmethod
    def list_all(
        user_performing_action: DATestUser,
    ) -> SkillsList:
        response = client.get(
            f"{API_SERVER_URL}/skills",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillsList)

    @staticmethod
    def list_for_user(
        user_performing_action: DATestUser,
    ) -> SkillsList:
        response = client.get(
            f"{API_SERVER_URL}/skills",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillsList)

    @staticmethod
    def get_for_user(
        skill_id: str | UUID,
        user_performing_action: DATestUser,
    ) -> SkillResponse:
        response = client.get(
            f"{API_SERVER_URL}/skills/{skill_id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def preview(
        skill_id: str | UUID,
        user_performing_action: DATestUser,
    ) -> SkillPreviewResponse:
        response = client.get(
            f"{API_SERVER_URL}/skills/{skill_id}/preview",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillPreviewResponse)

    @staticmethod
    def get_editable(
        skill_id: str | UUID,
        user_performing_action: DATestUser,
    ) -> SkillEditableDetailResponse:
        response = client.get(
            f"{API_SERVER_URL}/skills/custom/{skill_id}/edit",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillEditableDetailResponse)

    @staticmethod
    def share(
        skill: SkillResponse,
        user_performing_action: DATestUser,
        *,
        is_public: bool | None = None,
        public_permission: SkillSharePermission | None = None,
        user_shares: Sequence[SkillUserShareRequest] | None = None,
        group_shares: Sequence[SkillGroupShareRequest] | None = None,
    ) -> SkillResponse:
        share_req = SkillShareRequest(
            user_shares=list(user_shares) if user_shares is not None else None,
            group_shares=list(group_shares) if group_shares is not None else None,
            is_public=is_public,
            public_permission=public_permission,
        )

        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/share",
            json=share_req.model_dump(mode="json", exclude_none=True),
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def transfer_ownership(
        skill: SkillResponse,
        new_owner_user_id: UUID | str,
        user_performing_action: DATestUser,
    ) -> SkillResponse:
        transfer_req = TransferSkillOwnershipRequest(
            new_owner_user_id=UUID(str(new_owner_user_id))
        )
        response = client.post(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/transfer-ownership",
            json=transfer_req.model_dump(mode="json"),
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def create_personal(
        user_performing_action: DATestUser,
        *,
        slug: str | None = None,
        name: str | None = None,
        description: str | None = None,
        bundle_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> SkillResponse:
        slug = slug or f"personal-skill-{uuid4().hex[:8]}"
        if bundle_bytes is None:
            bundle_bytes = build_minimal_bundle(
                slug, name=name, description=description
            )

        headers = dict(user_performing_action.headers)
        headers.pop("Content-Type", None)

        response = client.post(
            f"{API_SERVER_URL}/skills/custom",
            files={
                "bundle": (
                    filename or f"{slug}.zip",
                    io.BytesIO(bundle_bytes),
                    "application/zip",
                )
            },
            headers=headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def replace_personal_bundle(
        skill: SkillResponse,
        bundle_bytes: bytes,
        user_performing_action: DATestUser,
    ) -> SkillResponse:
        headers = dict(user_performing_action.headers)
        headers.pop("Content-Type", None)

        response = client.put(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/bundle",
            files={
                "bundle": (
                    f"{skill.slug}.zip",
                    io.BytesIO(bundle_bytes),
                    "application/zip",
                )
            },
            headers=headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def patch_personal(
        skill: SkillResponse,
        user_performing_action: DATestUser,
        patch_req: SkillPatchRequest,
    ) -> SkillResponse:
        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            json=patch_req.model_dump(
                mode="json",
                exclude_unset=True,
            ),
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _response_model(response, SkillResponse)

    @staticmethod
    def delete_personal(
        skill: SkillResponse,
        user_performing_action: DATestUser,
    ) -> None:
        response = client.delete(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
