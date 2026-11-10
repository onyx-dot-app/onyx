"""Runtime storage outages must not permanently disable saved Skills."""

from typing import Literal
from unittest.mock import patch

import pytest
from azure.core.exceptions import ResourceNotFoundError
from botocore.exceptions import ClientError
from google.api_core.exceptions import NotFound
from sqlalchemy.orm import Session

from onyx.db.models import Skill, User
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api
from onyx.skills.push import _assemble_fileset
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    upload,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    tenant as tenant,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    user as user,
)


@pytest.mark.parametrize("provider", ["s3", "gcs", "azure"])
@pytest.mark.parametrize("metadata", ["unknown", "exists", "missing", "outage"])
def test_runtime_cloud_404_requires_confirmed_absence(
    session: Session,
    user: User,
    provider: Literal["s3", "gcs", "azure"],
    metadata: Literal["unknown", "exists", "missing", "outage"],
) -> None:
    response = api.create_custom_skill(
        upload(bundle("retryable-reader")), True, user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.current_version is not None
    version = skill.current_version
    original_file_id = version.bundle_file_id
    version.is_valid = None
    session.commit()
    error: Exception
    if provider == "s3":
        error = ClientError({"Error": {"Code": "404"}}, "GetObject")
    elif provider == "gcs":
        error = NotFound("Bucket unavailable")
    else:
        error = ResourceNotFoundError("Container unavailable")
    store = get_default_file_store()
    with (
        patch.object(store, "read_file", side_effect=error),
        patch.object(store, "get_file_size") as size,
    ):
        if metadata == "missing":
            size.side_effect = FileNotFoundError("Object is missing")
        elif metadata == "outage":
            size.side_effect = TimeoutError("Metadata service unavailable")
        else:
            size.return_value = 123 if metadata == "exists" else None
        assert _assemble_fileset([skill], user, session) == {}
    session.refresh(version)
    assert version.bundle_file_id == original_file_id
    if metadata == "missing":
        assert version.is_valid is False
    else:
        assert version.is_valid is None
        assert "retryable-reader/SKILL.md" in _assemble_fileset([skill], user, session)
        session.refresh(version)
        assert version.is_valid is True


@pytest.mark.parametrize(
    "error,expected",
    [
        (ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"), False),
        (FileNotFoundError("Missing PostgreSQL large object"), False),
        (ClientError({"Error": {"Code": "NoSuchBucket"}}, "GetObject"), None),
        (ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject"), None),
    ],
)
def test_runtime_definitive_storage_errors(
    session: Session, user: User, error: Exception, expected: bool | None
) -> None:
    response = api.create_custom_skill(
        upload(bundle("definitive-reader")), True, user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.current_version is not None
    version = skill.current_version
    version.is_valid = None
    session.commit()
    store = get_default_file_store()
    with (
        patch.object(store, "read_file", side_effect=error),
        patch.object(store, "get_file_size", return_value=None) as size,
    ):
        assert _assemble_fileset([skill], user, session) == {}
        # Only the pre-download size check; classification needs no metadata.
        size.assert_called_once_with(version.bundle_file_id)
    session.refresh(version)
    assert version.is_valid is expected
