import pytest

from ee.onyx.server.scim.filtering import parse_scim_filter
from ee.onyx.server.scim.filtering import ScimFilter
from ee.onyx.server.scim.filtering import ScimFilterOperator


class TestParseScimFilter:
    """Tests for SCIM filter expression parsing."""

    def test_eq_filter_double_quoted(self) -> None:
        result = parse_scim_filter('userName eq "john@example.com"')
        assert result == ScimFilter(
            attribute="userName",
            operator=ScimFilterOperator.EQUAL,
            value="john@example.com",
        )

    def test_eq_filter_single_quoted(self) -> None:
        result = parse_scim_filter("userName eq 'john@example.com'")
        assert result == ScimFilter(
            attribute="userName",
            operator=ScimFilterOperator.EQUAL,
            value="john@example.com",
        )

    def test_co_filter(self) -> None:
        result = parse_scim_filter('displayName co "Engineering"')
        assert result == ScimFilter(
            attribute="displayName",
            operator=ScimFilterOperator.CONTAINS,
            value="Engineering",
        )

    def test_sw_filter(self) -> None:
        result = parse_scim_filter('userName sw "admin"')
        assert result == ScimFilter(
            attribute="userName",
            operator=ScimFilterOperator.STARTS_WITH,
            value="admin",
        )

    def test_case_insensitive_operator(self) -> None:
        result = parse_scim_filter('userName EQ "test@example.com"')
        assert result is not None
        assert result.operator == ScimFilterOperator.EQUAL

    def test_external_id_filter(self) -> None:
        result = parse_scim_filter('externalId eq "abc-123"')
        assert result == ScimFilter(
            attribute="externalId",
            operator=ScimFilterOperator.EQUAL,
            value="abc-123",
        )

    def test_empty_value(self) -> None:
        result = parse_scim_filter('userName eq ""')
        assert result == ScimFilter(
            attribute="userName",
            operator=ScimFilterOperator.EQUAL,
            value="",
        )

    def test_whitespace_trimming(self) -> None:
        result = parse_scim_filter('  userName eq "test"  ')
        assert result is not None
        assert result.value == "test"

    @pytest.mark.parametrize(
        "filter_string",
        [
            None,
            "",
            "   ",
        ],
    )
    def test_empty_input_returns_none(self, filter_string: str | None) -> None:
        assert parse_scim_filter(filter_string) is None

    @pytest.mark.parametrize(
        "filter_string",
        [
            "userName",  # missing operator and value
            "userName eq",  # missing value
            'userName gt "5"',  # unsupported operator
            'userName ne "test"',  # unsupported operator
            "userName eq unquoted",  # unquoted value
            'a eq "x" and b eq "y"',  # compound filter not supported
        ],
    )
    def test_malformed_input_raises_value_error(self, filter_string: str) -> None:
        with pytest.raises(ValueError, match="Unsupported or malformed"):
            parse_scim_filter(filter_string)
