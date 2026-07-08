from __future__ import annotations

import io
import json
import zipfile
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.external_apps.api import create_built_in_external_app
from onyx.server.features.build.external_apps.api import create_custom_external_app
from onyx.server.features.build.external_apps.api import replace_custom_app_bundle
from onyx.server.features.build.external_apps.api import update_external_app_admin
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
)
from onyx.server.features.build.external_apps.models import ExternalAppAdminResponse
from onyx.server.features.build.external_apps.models import UpdateExternalAppRequest
from onyx.utils.encryption import is_masked_credential

_AUTH_TEMPLATE = {"Authorization": "Bearer {api_key}"}
_UPSTREAM = ["https://api.example.com/*"]


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _bundle_zip(*, with_skill_md: bool = True, marker: str = "v1") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if with_skill_md:
            zf.writestr(
                "SKILL.md",
                "---\nname: Bundle Name\ndescription: Bundle description\n---\n\nDo things.\n",
            )
        zf.writestr("helper.py", f"print('{marker}')\n")
    return buf.getvalue()


def _upload(
    filename: str, *, with_skill_md: bool = True, marker: str = "v1"
) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(_bundle_zip(with_skill_md=with_skill_md, marker=marker)),
        filename=filename,
    )


def _create(
    db_session: Session,
    test_user: User,
    slug: str,
    *,
    auth_template: str = json.dumps(_AUTH_TEMPLATE),
    organization_credentials: str = json.dumps({"api_key": "sk-test"}),
) -> ExternalAppAdminResponse:
    """Create a custom app with a valid default bundle."""
    return create_custom_external_app(
        name="My Form Name",
        description="",
        upstream_url_patterns=json.dumps(_UPSTREAM),
        auth_template=auth_template,
        organization_credentials=organization_credentials,
        enabled=True,
        bundle=_upload(f"{slug}.zip"),
        _=test_user,
        db_session=db_session,
    )


@pytest.fixture(autouse=True, scope="module")
def _ensure_bundle_store(initialize_file_store: None) -> None:  # noqa: ARG001
    """Create the bundle blob store before any test runs (create/edit save the
    uploaded bundle via ``ingest_skill_bundle``)."""


def test_create_persists_skill_and_app(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"

    resp = _create(db_session, test_user, slug)

    # Form name overrides the bundle's SKILL.md name; blank description falls
    # back to the bundle's parsed description.
    assert resp.app_type == ExternalAppType.CUSTOM
    assert resp.name == "My Form Name"
    assert resp.description == "Bundle description"
    assert resp.upstream_url_patterns == _UPSTREAM

    skill = db_session.scalar(select(Skill).where(Skill.slug == slug))
    assert skill is not None
    assert skill.built_in_skill_id is None
    assert skill.bundle_file_id  # bundle was stored
    assert skill.name == "My Form Name"

    app = db_session.scalar(select(ExternalApp).where(ExternalApp.skill_id == skill.id))
    assert app is not None
    assert app.auth_template == _AUTH_TEMPLATE
    # organization_credentials is encrypted at rest -> decrypt to compare.
    assert app.organization_credentials.get_value(apply_mask=False) == {
        "api_key": "sk-test"
    }

    db_session.execute(delete(Skill).where(Skill.slug == slug))
    db_session.commit()


def test_custom_app_glob_matches_deep_path(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom apps store their URL patterns as authored globs; the matcher
    translates them to regexes that cover deep paths (the Discord 401
    regression — ``/api/*`` must match ``/api/v10/...``)."""
    from onyx.sandbox_proxy.request_evaluator import resolve_app_for_url

    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"

    resp = _create(db_session, test_user, slug)
    # The glob is stored and round-tripped verbatim — no regex stored at rest.
    assert resp.upstream_url_patterns == _UPSTREAM

    app = db_session.scalar(select(ExternalApp).where(ExternalApp.id == resp.id))
    assert app is not None
    assert list(app.upstream_url_patterns) == _UPSTREAM
    # The matcher translates the glob, resolving a realistic deep path here.
    assert resolve_app_for_url("https://api.example.com/v10/users/@me", [app]) is app
    assert resolve_app_for_url("https://other.example.com/x", [app]) is None

    db_session.execute(delete(Skill).where(Skill.slug == slug))
    db_session.commit()


def test_create_rejects_wildcard_host_glob(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"

    with pytest.raises(OnyxError):
        create_custom_external_app(
            name="Wildcard Host",
            description="",
            upstream_url_patterns=json.dumps(["https://*.example.com/*"]),
            auth_template=json.dumps(_AUTH_TEMPLATE),
            organization_credentials=json.dumps({"api_key": "sk-test"}),
            enabled=True,
            bundle=_upload(f"{slug}.zip"),
            _=test_user,
            db_session=db_session,
        )
    # Rejected before persistence — no skill row created.
    assert db_session.scalar(select(Skill).where(Skill.slug == slug)) is None


def test_create_with_no_credentials(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"

    resp = _create(
        db_session,
        test_user,
        slug,
        auth_template=json.dumps({}),
        organization_credentials=json.dumps({}),
    )

    assert resp.auth_template == {}
    assert resp.organization_credentials == {}
    assert db_session.scalar(select(Skill).where(Skill.slug == slug)) is not None

    db_session.execute(delete(Skill).where(Skill.slug == slug))
    db_session.commit()


def test_edit_updates_config_and_replaces_bundle(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"

    created = _create(db_session, test_user, slug)
    skill = db_session.scalar(select(Skill).where(Skill.slug == slug))
    assert skill is not None
    original_bundle_id = skill.bundle_file_id

    edited = update_external_app_admin(
        external_app_id=created.id,
        request=UpdateExternalAppRequest(
            name="Renamed App",
            description="A new description",
            upstream_url_patterns=["https://api.example.com/v2/*"],
            auth_template=_AUTH_TEMPLATE,
            organization_credentials={},
        ),
        _=test_user,
        db_session=db_session,
    )

    assert edited.id == created.id
    assert edited.name == "Renamed App"
    assert edited.description == "A new description"
    assert edited.upstream_url_patterns == ["https://api.example.com/v2/*"]
    assert edited.organization_credentials == {}

    rebundled = replace_custom_app_bundle(
        external_app_id=created.id,
        bundle=_upload(f"{slug}.zip", marker="v2"),
        _=test_user,
        db_session=db_session,
    )
    # Bundle swap preserves the fields set by the PATCH above.
    assert rebundled.name == "Renamed App"

    db_session.expire_all()
    skill = db_session.scalar(select(Skill).where(Skill.slug == slug))
    assert skill is not None
    # Slug is stable across a bundle swap, but the blob changed.
    assert skill.name == "Renamed App"
    assert skill.bundle_file_id
    assert skill.bundle_file_id != original_bundle_id

    db_session.execute(delete(Skill).where(Skill.slug == slug))
    db_session.commit()


def test_admin_response_masks_secret_and_edit_preserves_it(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org credential secrets are masked in the admin response, and re-saving the
    masked placeholder (an edit that doesn't touch the secret) preserves the real
    stored value rather than overwriting it with the mask."""
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"
    raw_secret = "super-secret-client-value-1234567890"

    created = _create(
        db_session,
        test_user,
        slug,
        organization_credentials=json.dumps({"api_key": raw_secret}),
    )

    # The response must not echo the raw secret back to the client.
    returned = created.organization_credentials["api_key"]
    assert returned != raw_secret
    assert is_masked_credential(returned)

    # Edit, echoing the masked value back (the form was populated from the
    # masked response and the admin didn't change it).
    edited = update_external_app_admin(
        external_app_id=created.id,
        request=UpdateExternalAppRequest(
            name="My Form Name",
            upstream_url_patterns=_UPSTREAM,
            auth_template=_AUTH_TEMPLATE,
            organization_credentials={"api_key": returned},
        ),
        _=test_user,
        db_session=db_session,
    )
    assert is_masked_credential(edited.organization_credentials["api_key"])

    db_session.expire_all()
    app = db_session.scalar(select(ExternalApp).where(ExternalApp.id == created.id))
    assert app is not None
    # The stored secret is unchanged — the mask never overwrote it.
    assert app.organization_credentials.get_value(apply_mask=False) == {
        "api_key": raw_secret
    }

    db_session.execute(delete(Skill).where(Skill.slug == slug))
    db_session.commit()


def test_create_rejects_bundle_without_skill_md(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"

    with pytest.raises(OnyxError):
        create_custom_external_app(
            name="No Skill",
            description="",
            upstream_url_patterns=json.dumps(_UPSTREAM),
            auth_template=json.dumps(_AUTH_TEMPLATE),
            organization_credentials=json.dumps({}),
            enabled=True,
            bundle=_upload(f"{slug}.zip", with_skill_md=False),
            _=test_user,
            db_session=db_session,
        )

    assert db_session.scalar(select(Skill).where(Skill.slug == slug)) is None


def test_create_requires_bundle(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    with pytest.raises(OnyxError):
        create_custom_external_app(
            name="No Bundle",
            description="",
            upstream_url_patterns=json.dumps(_UPSTREAM),
            auth_template=json.dumps(_AUTH_TEMPLATE),
            organization_credentials=json.dumps({}),
            enabled=True,
            bundle=None,
            _=test_user,
            db_session=db_session,
        )


def test_create_rejects_bundle_over_skill_upload_size_limit(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    monkeypatch.setattr("onyx.skills.bundle.DEFAULT_TOTAL_MAX_BYTES", 1)
    slug = f"custom-test-{uuid4().hex[:8]}"

    with pytest.raises(OnyxError) as exc:
        create_custom_external_app(
            name="Too Large",
            description="",
            upstream_url_patterns=json.dumps(_UPSTREAM),
            auth_template=json.dumps(_AUTH_TEMPLATE),
            organization_credentials=json.dumps({}),
            enabled=True,
            bundle=_upload(f"{slug}.zip"),
            _=test_user,
            db_session=db_session,
        )

    assert exc.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert db_session.scalar(select(Skill).where(Skill.slug == slug)) is None


def test_replace_rejects_bundle_over_skill_upload_size_limit(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )
    slug = f"custom-test-{uuid4().hex[:8]}"
    created = _create(db_session, test_user, slug)

    monkeypatch.setattr("onyx.skills.bundle.DEFAULT_TOTAL_MAX_BYTES", 1)

    with pytest.raises(OnyxError) as exc:
        replace_custom_app_bundle(
            external_app_id=created.id,
            bundle=_upload(f"{slug}.zip", marker="v2"),
            _=test_user,
            db_session=db_session,
        )

    assert exc.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE

    db_session.execute(delete(Skill).where(Skill.slug == slug))
    db_session.commit()


def test_create_cleans_up_blob_on_failure(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skill_to_affected_sandboxes",
        _noop,
    )

    def _boom(*_args: object, **_kwargs: object) -> ExternalApp:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "forced failure")

    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.create_external_app",
        _boom,
    )

    deleted: list[str] = []
    monkeypatch.setattr(
        "onyx.skills.ingest.delete_bundle_blob",
        lambda _fs, file_id: deleted.append(file_id),
    )

    slug = f"custom-test-{uuid4().hex[:8]}"
    with pytest.raises(OnyxError):
        _create(db_session, test_user, slug)

    # The bundle was stored during ingest, so the post-failure cleanup must run.
    assert len(deleted) == 1


def test_json_admin_apps_rejects_custom(
    db_session: Session,
    test_user: User,
) -> None:
    with pytest.raises(OnyxError):
        create_built_in_external_app(
            request=CreateBuiltInExternalAppRequest(
                name="Nope",
                description="",
                enabled=True,
                app_type=ExternalAppType.CUSTOM,
                upstream_url_patterns=_UPSTREAM,
                auth_template=_AUTH_TEMPLATE,
                organization_credentials={},
            ),
            _=test_user,
            db_session=db_session,
        )
