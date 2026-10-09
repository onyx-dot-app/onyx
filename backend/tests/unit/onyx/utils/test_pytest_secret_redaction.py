from _pytest._io.saferepr import saferepr

from tests.utils.pytest_secrets import RedactedDict

SAMPLE_SECRET = "sensitive-test-value"


def test_redacted_dict_hides_values_from_pytest_repr() -> None:
    secrets = RedactedDict({"credential": SAMPLE_SECRET})

    assert secrets["credential"] == SAMPLE_SECRET
    assert SAMPLE_SECRET not in repr(secrets)
    assert SAMPLE_SECRET not in saferepr(secrets)
