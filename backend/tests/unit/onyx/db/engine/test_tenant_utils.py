"""Tests for onyx.db.engine.tenant_utils."""

import pytest

from onyx.db.engine.tenant_utils import validate_tenant_id


class TestValidateTenantId:
    """Tests for validate_tenant_id - validates tenant ID format for SQL safety."""

    @pytest.mark.parametrize(
        "tenant_id",
        [
            # Standard UUID format
            "tenant_0aef62e7-9fbf-4bb6-8894-f1441fca6745",
            "tenant_abcd1234-5678-90ab-cdef-1234567890ab",
            "tenant_00000000-0000-0000-0000-000000000000",
            "tenant_ffffffff-ffff-ffff-ffff-ffffffffffff",
            # AWS instance ID format
            "tenant_i-0d8d7eaa21f5f2fae",
            "tenant_i-0123456789abcdef0",
            "tenant_i-abc",
            # Staff dev tenant
            "tenant_dev",
        ],
    )
    def test_valid_tenant_ids(self, tenant_id: str) -> None:
        """Valid tenant IDs should pass validation."""
        assert validate_tenant_id(tenant_id) is True

    @pytest.mark.parametrize(
        "tenant_id,description",
        [
            # Missing tenant_ prefix
            ("0aef62e7-9fbf-4bb6-8894-f1441fca6745", "missing prefix"),
            ("public", "reserved schema name"),
            ("pg_catalog", "system schema"),
            # Invalid formats
            ("tenant_abc123", "not UUID or instance ID format"),
            ("tenant_", "empty after prefix"),
            ("tenant_i-", "empty instance ID"),
            # SQL injection attempts
            ("tenant_; DROP TABLE users;--", "SQL injection with semicolon"),
            ('tenant_" OR 1=1--', "SQL injection with quote"),
            ("tenant_abc'; DROP SCHEMA public;--", "SQL injection attempt"),
            # Other invalid inputs
            ("tenant_ABCD1234-5678-90AB-CDEF-1234567890AB", "uppercase not allowed"),
            ("../../../etc/passwd", "path traversal"),
            ("", "empty string"),
            ("tenant_i-GHIJ", "invalid hex in instance ID"),
        ],
    )
    def test_invalid_tenant_ids(self, tenant_id: str, description: str) -> None:
        """Invalid tenant IDs should fail validation."""
        assert validate_tenant_id(tenant_id) is False, f"Should reject: {description}"

    def test_uuid_must_be_complete(self) -> None:
        """UUID must have all sections with correct lengths."""
        # Too short
        assert validate_tenant_id("tenant_0aef62e7-9fbf-4bb6-8894") is False
        # Too long
        assert (
            validate_tenant_id("tenant_0aef62e7-9fbf-4bb6-8894-f1441fca6745-extra")
            is False
        )
        # Wrong section lengths
        assert validate_tenant_id("tenant_0aef62e7-9fbf-4bb6-8894-f1441fca674") is False
