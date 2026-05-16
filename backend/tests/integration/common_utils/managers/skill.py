import io
import json
import zipfile
from uuid import uuid4

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestSkill
from tests.integration.common_utils.test_models import DATestUser


def build_minimal_bundle(slug: str) -> bytes:
    """Build a minimal valid skill bundle zip with SKILL.md."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            f"---\nname: {slug}\ndescription: Test skill {slug}\n---\n\nSkill instructions.",
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
    ) -> DATestSkill:
        slug = slug or f"test-skill-{uuid4().hex[:8]}"
        name = name or f"Test Skill {slug}"
        description = description or f"Description for {slug}"
        if bundle_bytes is None:
            bundle_bytes = build_minimal_bundle(slug)

        response = requests.post(
            f"{API_SERVER_URL}/admin/skills/custom",
            data={
                "slug": slug,
                "name": name,
                "description": description,
                "is_public": str(is_public).lower(),
                "group_ids": json.dumps(group_ids or []),
            },
            files={
                "bundle": (
                    f"{slug}.zip",
                    io.BytesIO(bundle_bytes),
                    "application/zip",
                )
            },
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
        )

    @staticmethod
    def patch_custom(
        skill: DATestSkill,
        user_performing_action: DATestUser,
        **fields: object,
    ) -> DATestSkill:
        response = requests.patch(
            f"{API_SERVER_URL}/admin/skills/custom/{skill.id}",
            json=fields,
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
        )

    @staticmethod
    def replace_bundle(
        skill: DATestSkill,
        bundle_bytes: bytes,
        user_performing_action: DATestUser,
    ) -> DATestSkill:
        response = requests.put(
            f"{API_SERVER_URL}/admin/skills/custom/{skill.id}/bundle",
            files={
                "bundle": (
                    f"{skill.slug}.zip",
                    io.BytesIO(bundle_bytes),
                    "application/zip",
                )
            },
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
        )

    @staticmethod
    def replace_grants(
        skill: DATestSkill,
        group_ids: list[int],
        user_performing_action: DATestUser,
    ) -> DATestSkill:
        response = requests.put(
            f"{API_SERVER_URL}/admin/skills/custom/{skill.id}/grants",
            json={"group_ids": group_ids},
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
        )

    @staticmethod
    def delete_custom(
        skill: DATestSkill,
        user_performing_action: DATestUser,
    ) -> None:
        response = requests.delete(
            f"{API_SERVER_URL}/admin/skills/custom/{skill.id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

    @staticmethod
    def list_all(
        user_performing_action: DATestUser,
    ) -> dict:
        response = requests.get(
            f"{API_SERVER_URL}/admin/skills",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def list_for_user(
        user_performing_action: DATestUser,
    ) -> dict:
        response = requests.get(
            f"{API_SERVER_URL}/skills",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()
