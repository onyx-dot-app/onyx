"""Unit tests for the S3 Files backend.

We mock boto3 rather than pull in ``moto`` as a test dep — the surface
we need to validate is the key layout and the access-point lookup
semantics, both of which are pure call-shape assertions.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.skills.backends.base import SkillFile
from onyx.skills.backends.s3_files import S3FilesSkillsBackend


@pytest.fixture
def fake_s3() -> MagicMock:
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = []
    return client


@pytest.fixture
def fake_efs() -> MagicMock:
    return MagicMock()


@pytest.fixture
def backend(fake_s3: MagicMock, fake_efs: MagicMock) -> Iterator[S3FilesSkillsBackend]:
    with patch("onyx.skills.backends.s3_files.boto3") as boto3_mock:
        boto3_mock.client.side_effect = lambda name, **_: (
            fake_s3 if name == "s3" else fake_efs
        )
        yield S3FilesSkillsBackend(
            bucket="skills-bucket",
            file_system_id="fs-1234",
            region_name="us-west-2",
        )


def test_write_builtin_uses_builtins_prefix(
    backend: S3FilesSkillsBackend, fake_s3: MagicMock
) -> None:
    backend.write_builtin(
        "pptx", [SkillFile(relative_path="SKILL.md", content=b"# pptx")]
    )
    fake_s3.put_object.assert_called_once_with(
        Bucket="skills-bucket",
        Key="_builtins/pptx/SKILL.md",
        Body=b"# pptx",
    )


def test_write_custom_uses_tenant_scoped_key(
    backend: S3FilesSkillsBackend, fake_s3: MagicMock
) -> None:
    backend.write_custom(
        "tenant-a",
        "my-skill",
        [SkillFile(relative_path="scripts/run.sh", content=b"#!/bin/sh")],
    )
    fake_s3.put_object.assert_called_once_with(
        Bucket="skills-bucket",
        Key="tenants/tenant-a/_custom/my-skill/scripts/run.sh",
        Body=b"#!/bin/sh",
    )


def test_key_prefix_applied_to_all_writes(
    fake_s3: MagicMock, fake_efs: MagicMock
) -> None:
    with patch("onyx.skills.backends.s3_files.boto3") as boto3_mock:
        boto3_mock.client.side_effect = lambda name, **_: (
            fake_s3 if name == "s3" else fake_efs
        )
        b = S3FilesSkillsBackend(
            bucket="dev-bucket",
            key_prefix="dev/alice",
            file_system_id="fs-1234",
        )
        b.write_builtin("pptx", [SkillFile(relative_path="SKILL.md", content=b"x")])
    fake_s3.put_object.assert_called_once_with(
        Bucket="dev-bucket",
        Key="dev/alice/_builtins/pptx/SKILL.md",
        Body=b"x",
    )


def test_ensure_access_point_returns_existing_match(
    backend: S3FilesSkillsBackend, fake_efs: MagicMock
) -> None:
    fake_efs.get_paginator.return_value.paginate.return_value = [
        {
            "AccessPoints": [
                {
                    "AccessPointId": "fsap-existing",
                    "Tags": [
                        {"Key": "onyx-tenant-id", "Value": "tenant-a"},
                    ],
                }
            ]
        }
    ]

    ap_id = backend.ensure_access_point("tenant-a")
    assert ap_id == "fsap-existing"
    fake_efs.create_access_point.assert_not_called()


def test_ensure_access_point_creates_when_missing(
    backend: S3FilesSkillsBackend, fake_efs: MagicMock
) -> None:
    fake_efs.get_paginator.return_value.paginate.return_value = [{"AccessPoints": []}]
    fake_efs.create_access_point.return_value = {"AccessPointId": "fsap-new"}

    ap_id = backend.ensure_access_point("tenant-a")
    assert ap_id == "fsap-new"
    call: dict[str, Any] = fake_efs.create_access_point.call_args.kwargs
    assert call["FileSystemId"] == "fs-1234"
    assert call["RootDirectory"]["Path"] == "/tenants/tenant-a"
    # Tag-based lookup must round-trip.
    assert any(
        t == {"Key": "onyx-tenant-id", "Value": "tenant-a"} for t in call["Tags"]
    )


@pytest.mark.parametrize(
    "bad_path",
    [
        "/abs/SKILL.md",
        "../escape",
        "scripts/../../boom",
        "",
        "scripts\\nope",
    ],
)
def test_rejects_traversal_paths(backend: S3FilesSkillsBackend, bad_path: str) -> None:
    with pytest.raises(ValueError):
        backend.write_builtin("x", [SkillFile(relative_path=bad_path, content=b"")])
