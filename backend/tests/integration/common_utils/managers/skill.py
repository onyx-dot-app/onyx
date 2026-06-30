import io
import zipfile
from typing import Any
from uuid import uuid4

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestSkill
from tests.integration.common_utils.test_models import DATestUser


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


def _skill_from_response(data: dict[str, Any]) -> DATestSkill:
    return DATestSkill(
        id=data["id"],
        slug=data["slug"],
        name=data["name"],
        description=data["description"],
        is_public=data["is_public"],
        public_permission=data.get("public_permission"),
        enabled=data["enabled"],
        user_shares=data.get("user_shares", []),
        group_shares=data.get("group_shares", []),
        is_personal=data.get("is_personal", False),
        user_permission=data.get("user_permission"),
    )


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
    ) -> DATestSkill:
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
        skill = _skill_from_response(response.json())

        if is_public or group_ids:
            share_response = client.patch(
                f"{API_SERVER_URL}/skills/custom/{skill.id}/share",
                json={
                    "is_public": is_public,
                    "group_shares": [
                        {"group_id": group_id, "permission": "VIEWER"}
                        for group_id in group_ids or []
                    ],
                },
                headers=user_performing_action.headers,
            )
            share_response.raise_for_status()
            return _skill_from_response(share_response.json())

        return skill

    @staticmethod
    def patch_custom(
        skill: DATestSkill,
        user_performing_action: DATestUser,
        **fields: object,
    ) -> DATestSkill:
        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            json=fields,
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _skill_from_response(response.json())

    @staticmethod
    def replace_bundle(
        skill: DATestSkill,
        bundle_bytes: bytes,
        user_performing_action: DATestUser,
    ) -> DATestSkill:
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
        return _skill_from_response(response.json())

    @staticmethod
    def replace_group_shares(
        skill: DATestSkill,
        group_ids: list[int],
        user_performing_action: DATestUser,
    ) -> DATestSkill:
        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}/share",
            json={
                "group_shares": [
                    {"group_id": group_id, "permission": "VIEWER"}
                    for group_id in group_ids
                ]
            },
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _skill_from_response(response.json())

    @staticmethod
    def delete_custom(
        skill: DATestSkill,
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
    ) -> dict:
        response = client.get(
            f"{API_SERVER_URL}/skills",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def list_for_user(
        user_performing_action: DATestUser,
    ) -> dict:
        response = client.get(
            f"{API_SERVER_URL}/skills",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_for_user(
        skill_id: str,
        user_performing_action: DATestUser,
    ) -> dict:
        response = client.get(
            f"{API_SERVER_URL}/skills/{skill_id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def create_personal(
        user_performing_action: DATestUser,
        *,
        slug: str | None = None,
        name: str | None = None,
        description: str | None = None,
        bundle_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> DATestSkill:
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
        return _skill_from_response(response.json())

    @staticmethod
    def replace_personal_bundle(
        skill: DATestSkill,
        bundle_bytes: bytes,
        user_performing_action: DATestUser,
    ) -> DATestSkill:
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
        return _skill_from_response(response.json())

    @staticmethod
    def patch_personal(
        skill: DATestSkill,
        user_performing_action: DATestUser,
        **fields: object,
    ) -> DATestSkill:
        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            json=fields,
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return _skill_from_response(response.json())

    @staticmethod
    def delete_personal(
        skill: DATestSkill,
        user_performing_action: DATestUser,
    ) -> None:
        response = client.delete(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
