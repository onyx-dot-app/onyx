"""The HTTPException check flags raises, subclasses and status constants from
fastapi and starlette, leaves handlers and same-named symbols alone, honours
the allow marker only with a reason, and ratchets each file against the baseline."""

from pathlib import Path

import pytest
from scripts import check_no_http_exception

_CLEAN = "backend/onyx/server/clean.py"
_LEGACY = "backend/onyx/server/legacy.py"
_RAISE = "    raise HTTPException(status_code=404, detail='x')\n"
_ONE_RAISE = "from fastapi import HTTPException\n\ndef f() -> None:\n" + _RAISE


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import HTTPException\nraise HTTPException(status_code=404)",
        "from fastapi import HTTPException\nraise HTTPException",
        "from fastapi import HTTPException as E\nraise E(status_code=404)",
        "from fastapi.exceptions import HTTPException\nerr = HTTPException(404)",
        "from starlette.exceptions import HTTPException\nraise HTTPException(404)",
        "import fastapi\nraise fastapi.HTTPException(status_code=404)",
        "from fastapi import HTTPException\nclass E(HTTPException): ...",
        "from fastapi import status\ncode = status.HTTP_404_NOT_FOUND",
        "from starlette import status as s\ncode = s.HTTP_404_NOT_FOUND",
        "from starlette.status import HTTP_404_NOT_FOUND\ncode = HTTP_404_NOT_FOUND",
        "import starlette.status\ncode = starlette.status.HTTP_404_NOT_FOUND",
        "from fastapi import status\ncode = status.WS_1008_POLICY_VIOLATION",
    ],
)
def test_violation_is_flagged(source: str) -> None:
    assert check_no_http_exception.find_violations(source) == [2]


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import HTTPException\ntry:\n    f()\nexcept HTTPException:\n    raise",
        "from fastapi import HTTPException\nok = isinstance(e, HTTPException)",
        "import discord\ntry:\n    f()\nexcept discord.HTTPException:\n    pass",
        "from discord import HTTPException\nraise HTTPException(response, 'x')",
        "from .errors import HTTPException\nraise HTTPException(404)",
        "from onyx.x import IndexStatus\nstatus = IndexStatus()\nstatus.HTTP_1 = 2",
        "from fastapi import status\nstatus = f()\nstatus.total_documents = 3",
        "from onyx.error_handling.exceptions import OnyxError\nraise OnyxError(code)",
        '"""Raises HTTPException(401) from fastapi."""',
    ],
)
def test_other_use_is_not_flagged(source: str) -> None:
    assert check_no_http_exception.find_violations(source) == []


def test_each_violation_is_counted() -> None:
    source = (
        "from fastapi import HTTPException, status\n"
        "raise HTTPException(\n"
        "    status_code=status.HTTP_403_FORBIDDEN,\n"
        ")\n"
        "raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)\n"
    )
    assert check_no_http_exception.find_violations(source) == [2, 3, 5, 5]


@pytest.mark.parametrize(
    "source",
    [
        "raise HTTPException(404)  # http-exception: allow fastapi-users needs it",
        "# http-exception: allow fastapi-users needs it\nraise HTTPException(404)",
        "# http-exception: allow the reason runs over\n# two lines\nraise HTTPException(404)",
        "raise HTTPException(\n    404,  # http-exception: allow fastapi-users needs it\n)",
        "# http-exception: allow handler registration\ncodes = (\n    status.HTTP_400_BAD_REQUEST,\n    status.HTTP_404_NOT_FOUND,\n)",
    ],
)
def test_marker_with_reason_allows(source: str) -> None:
    imports = "from fastapi import HTTPException, status\n"
    assert check_no_http_exception.find_violations(imports + source) == []


@pytest.mark.parametrize(
    "source",
    [
        "raise HTTPException(404)  # http-exception: allow",
        "# http-exception: allow it\n\nraise HTTPException(404)",
        "# http-exception: allow it\ndef f() -> None:\n    raise HTTPException(404)",
        "raise HTTPException(404)\n# http-exception: allow it",
        "raise HTTPException(404, '# http-exception: allow it')",
        "x = [\n    f(),  # http-exception: allow it\n    HTTPException(404),\n]",
        "x = [\n    HTTPException(404),\n]  # http-exception: allow it",
        "@router.get('/x', status_code=E(404))\ndef f() -> None:\n    # http-exception: allow it\n    return None",
    ],
)
def test_marker_without_reason_or_out_of_place_does_not_allow(source: str) -> None:
    imports = (
        "from fastapi import HTTPException\nfrom fastapi import HTTPException as E\n"
    )
    assert len(check_no_http_exception.find_violations(imports + source)) == 1


def test_nested_import_does_not_hide_a_violation() -> None:
    source = (
        "from fastapi import HTTPException\n"
        "def f() -> None:\n"
        "    from discord import HTTPException\n"
        "raise HTTPException(404)\n"
    )
    assert check_no_http_exception.find_violations(source) == [4]


def _repo(tmp_path: Path, files: dict[str, str], baseline: str) -> Path:
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    baseline_path = tmp_path / "baseline.txt"
    baseline_path.write_text("# header\n" + baseline)
    return baseline_path


def _run(tmp_path: Path, baseline_path: Path, *flags: str) -> int:
    argv = ["--baseline", str(baseline_path), *flags]
    return check_no_http_exception.main(argv, repo_root=tmp_path)


def test_tree_at_baseline_passes(tmp_path: Path) -> None:
    files = {_CLEAN: "x = 1\n", _LEGACY: _ONE_RAISE}
    baseline_path = _repo(tmp_path, files, f"{_LEGACY} 1\n")
    assert _run(tmp_path, baseline_path) == 0


def test_new_violation_in_clean_file_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {_CLEAN: _ONE_RAISE, _LEGACY: _ONE_RAISE}
    baseline_path = _repo(tmp_path, files, f"{_LEGACY} 1\n")
    assert _run(tmp_path, baseline_path) == 1
    output = capsys.readouterr().out
    assert f"{_CLEAN}:4" in output
    assert _LEGACY not in output
    assert "OnyxErrorCode" in output
    assert "status_code_override" in output
    assert "backend/AGENTS.md" in output


def test_new_violation_in_baselined_file_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_path = _repo(tmp_path, {_LEGACY: _ONE_RAISE + _RAISE}, f"{_LEGACY} 1\n")
    assert _run(tmp_path, baseline_path) == 1
    assert "2 violations, baseline allows 1" in capsys.readouterr().out


def test_removed_violation_asks_for_a_lower_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_path = _repo(tmp_path, {_LEGACY: _ONE_RAISE}, f"{_LEGACY} 2\n")
    assert _run(tmp_path, baseline_path) == 1
    assert "--write-baseline" in capsys.readouterr().out


def test_deleted_baselined_file_fails(tmp_path: Path) -> None:
    baseline_path = _repo(tmp_path, {_CLEAN: "x = 1\n"}, f"{_LEGACY} 1\n")
    assert _run(tmp_path, baseline_path) == 1


def test_files_out_of_scope_are_ignored(tmp_path: Path) -> None:
    files = {
        "backend/tests/unit/test_x.py": _ONE_RAISE,
        "backend/model_server/x.py": _ONE_RAISE,
        check_no_http_exception.SKIP_PREFIXES[0] + "server.py": _ONE_RAISE,
    }
    assert _run(tmp_path, _repo(tmp_path, files, "")) == 0


def test_write_baseline_round_trips(tmp_path: Path) -> None:
    files = {_LEGACY: _ONE_RAISE + _RAISE, _CLEAN: "x = 1\n"}
    baseline_path = _repo(tmp_path, files, "")
    assert _run(tmp_path, baseline_path) == 1
    assert _run(tmp_path, baseline_path, "--write-baseline") == 0
    assert check_no_http_exception.read_baseline(baseline_path) == {_LEGACY: 2}
    assert _run(tmp_path, baseline_path) == 0


@pytest.mark.parametrize(
    "rows",
    [
        f"{_LEGACY}\n",
        f"{_LEGACY} one\n",
        f"{_LEGACY} 1\n{_LEGACY} 2\n",
        "<<<<<<< HEAD\n",
    ],
)
def test_malformed_baseline_is_rejected(tmp_path: Path, rows: str) -> None:
    baseline_path = _repo(tmp_path, {_LEGACY: _ONE_RAISE}, rows)
    with pytest.raises(SystemExit, match="--write-baseline"):
        _run(tmp_path, baseline_path)


def test_indented_comment_in_baseline_is_skipped(tmp_path: Path) -> None:
    baseline_path = _repo(tmp_path, {_LEGACY: _ONE_RAISE}, f"  # note\n\n{_LEGACY} 1\n")
    assert _run(tmp_path, baseline_path) == 0


def test_unparseable_file_is_named(tmp_path: Path) -> None:
    baseline_path = _repo(tmp_path, {_CLEAN: "raise HTTPException(\n"}, "")
    with pytest.raises(SystemExit, match=_CLEAN):
        _run(tmp_path, baseline_path)


def test_current_tree_matches_the_committed_baseline() -> None:
    assert check_no_http_exception.main([]) == 0
