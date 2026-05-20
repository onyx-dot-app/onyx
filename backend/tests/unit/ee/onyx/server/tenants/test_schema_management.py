"""Tests for schema management functions."""

import pytest

from ee.onyx.server.tenants.schema_management import drop_schema


class TestDropSchemaValidation:
    """Tests for drop_schema input validation (no DB required - fails before SQL)."""

    @pytest.mark.parametrize(
        "dangerous_input,description",
        [
            ("public", "system schema"),
            ("pg_catalog", "postgres catalog"),
            ("tenant_; DROP TABLE users;--", "SQL injection with semicolon"),
            ('tenant_" OR 1=1--', "SQL injection with quote"),
            ("tenant_abc123", "invalid format - not UUID"),
            ("", "empty string"),
        ],
    )
    def test_drop_schema_rejects_invalid_inputs(
        self, dangerous_input: str, description: str
    ) -> None:
        """drop_schema should reject invalid tenant IDs before any SQL runs."""
        with pytest.raises(ValueError, match="Invalid tenant_id format") as exc_info:
            drop_schema(dangerous_input)
        assert dangerous_input in str(exc_info.value), (
            f"Error should include input ({description})"
        )
