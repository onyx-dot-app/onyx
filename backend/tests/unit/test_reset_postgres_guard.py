import pytest

from tests.integration.common_utils.reset import reset_postgres


@pytest.mark.parametrize("value", [None, "", "   "])
def test_reset_postgres_refuses_without_postgres_db_env(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("POSTGRES_DB", raising=False)
    else:
        monkeypatch.setenv("POSTGRES_DB", value)

    with pytest.raises(RuntimeError, match="POSTGRES_DB"):
        reset_postgres()
