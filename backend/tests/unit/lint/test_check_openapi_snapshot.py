from pathlib import Path

import pytest
from lint import check_openapi_snapshot


@pytest.mark.parametrize("existing_snapshot", ['{"properties":{"tools":{}}}\n', None])
def test_snapshot_drift_fails_until_regenerated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    existing_snapshot: str | None,
) -> None:
    monkeypatch.setattr(check_openapi_snapshot, "ROOT", tmp_path)
    ee_package = tmp_path / "backend/ee/onyx"
    ee_package.mkdir(parents=True)
    (ee_package / "__init__.py").touch()
    snapshot = tmp_path / "backend/schema/openapi.json"
    if existing_snapshot is not None:
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text(existing_snapshot, encoding="utf-8")

    def generate(output: Path) -> None:
        output.write_text('{"properties":{"tool_ids":{}}}\n', encoding="utf-8")

    monkeypatch.setattr(check_openapi_snapshot, "generate", generate)

    assert check_openapi_snapshot.main(["--hook", "backend/onyx/models.py"]) == 1
    assert (
        "python3 backend/lint/check_openapi_snapshot.py --write"
        in capsys.readouterr().out
    )
    assert snapshot.exists() == (existing_snapshot is not None)
    if existing_snapshot is not None:
        assert snapshot.read_text(encoding="utf-8") == existing_snapshot

    assert check_openapi_snapshot.main(["--write"]) == 0
    assert '"tool_ids"' in snapshot.read_text(encoding="utf-8")
    assert check_openapi_snapshot.main(["--hook", "backend/onyx/models.py"]) == 0
