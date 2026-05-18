import pytest

from onyx.connectors.salesforce.utils import is_valid_sf_identifier
from onyx.connectors.salesforce.utils import validate_sf_identifier


class TestSfIdentifier:
    @pytest.mark.parametrize(
        "name",
        [
            "Account",
            "Contact",
            "User",
            "MyCustomObject__c",
            "ns__MyCustomObject__c",
            "LastModifiedDate",
            "Custom_Field_99",
            "a",
        ],
    )
    def test_valid(self, name: str) -> None:
        assert is_valid_sf_identifier(name) is True
        assert validate_sf_identifier(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "1Account",  # must start with a letter
            "_leading_underscore",
            "Account'",
            "Account; DROP TABLE X",
            "Account WHERE 1=1",
            "Account--",
            "Acc ount",  # whitespace
            "Account/*",
            'Account"',
            "Account)",
        ],
    )
    def test_invalid(self, name: str) -> None:
        assert is_valid_sf_identifier(name) is False
        with pytest.raises(ValueError):
            validate_sf_identifier(name)
