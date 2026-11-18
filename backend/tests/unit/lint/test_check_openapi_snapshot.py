from pathlib import Path

import pytest
from lint import check_openapi_snapshot


def test_snapshot_drift_fails_until_regenerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_openapi_snapshot, "ROOT", tmp_path)
    snapshot = tmp_path / "backend/openapi.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('{"properties":{"tools":{}}}\n', encoding="utf-8")

    def generate(output: Path) -> None:
        output.write_text('{"properties":{"tool_ids":{}}}\n', encoding="utf-8")

    monkeypatch.setattr(check_openapi_snapshot, "generate", generate)

    assert check_openapi_snapshot.main(["--hook", "backend/onyx/models.py"]) == 1
    assert (
        "python3 backend/lint/check_openapi_snapshot.py --write"
        in capsys.readouterr().out
    )
    assert '"tools"' in snapshot.read_text(encoding="utf-8")

    assert check_openapi_snapshot.main(["--write"]) == 0
    assert '"tool_ids"' in snapshot.read_text(encoding="utf-8")
    assert check_openapi_snapshot.main(["--hook", "backend/onyx/models.py"]) == 0
