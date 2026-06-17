import io
import json
import zipfile
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
            f"{API_SERVER_URL}/admin/skills/custom",
            data={
                "is_public": str(is_public).lower(),
                "group_ids": json.dumps(group_ids or []),
            },
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
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
            is_personal=data.get("is_personal", False),
        )

    @staticmethod
    def patch_custom(
        skill: DATestSkill,
        user_performing_action: DATestUser,
        **fields: object,
    ) -> DATestSkill:
        response = client.patch(
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
            is_personal=data.get("is_personal", False),
        )

    @staticmethod
    def replace_bundle(
        skill: DATestSkill,
        bundle_bytes: bytes,
        user_performing_action: DATestUser,
    ) -> DATestSkill:
        headers = dict(user_performing_action.headers)
        headers.pop("Content-Type", None)

        response = client.put(
            f"{API_SERVER_URL}/admin/skills/custom/{skill.id}/bundle",
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
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
            is_personal=data.get("is_personal", False),
        )

    @staticmethod
    def replace_grants(
        skill: DATestSkill,
        group_ids: list[int],
        user_performing_action: DATestUser,
    ) -> DATestSkill:
        response = client.put(
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
            is_personal=data.get("is_personal", False),
        )

    @staticmethod
    def delete_custom(
        skill: DATestSkill,
        user_performing_action: DATestUser,
    ) -> None:
        response = client.delete(
            f"{API_SERVER_URL}/admin/skills/custom/{skill.id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

    @staticmethod
    def list_all(
        user_performing_action: DATestUser,
    ) -> dict:
        response = client.get(
            f"{API_SERVER_URL}/admin/skills",
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
        slug_or_id: str,
        user_performing_action: DATestUser,
    ) -> dict:
        response = client.get(
            f"{API_SERVER_URL}/skills/{slug_or_id}",
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
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
            is_personal=data.get("is_personal", False),
        )

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
        data = response.json()
        return DATestSkill(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            is_public=data["is_public"],
            enabled=data["enabled"],
            granted_group_ids=data.get("granted_group_ids", []),
            is_personal=data.get("is_personal", False),
        )

    @staticmethod
    def patch_personal(
        skill: DATestSkill,
        user_performing_action: DATestUser,
        *,
        enabled: bool,
    ) -> DATestSkill:
        response = client.patch(
            f"{API_SERVER_URL}/skills/custom/{skill.id}",
            json={"enabled": enabled},
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
            is_personal=data.get("is_personal", False),
        )

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
