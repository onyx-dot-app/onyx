from pathlib import Path

from lint.check_test_flakes import check, python_findings


def test_python_calls_and_markers() -> None:
    source = """
from time import sleep as pause
import pytest as p
pause(1)
pause(1)  # test-flakes: allow exercise an actual timeout
@p.mark.skip
def test_bare(): pass
@p.mark.skipif(False, reason=f"Requires {platform} support")
def test_reason(): pass
p.skip(reason=" ")
p.skip("Service unavailable")
p.mark.skip(reason="test-flakes: allow")
p.skip(f"{env_name} is not set.")
p.skip(f"{dynamic_reason}")
"""
    assert sorted(python_findings(source)) == [
        (4, "sleep", False),
        (5, "sleep", True),
        (6, "skip", False),
        (8, "skip", True),
        (10, "skip", False),
        (11, "skip", True),
        (12, "skip", True),
        (13, "skip", True),
        (14, "skip", False),
    ]


def test_sleep_and_skip_counts_ratchet_independently(tmp_path: Path) -> None:
    file = tmp_path / "backend/tests/test_example.py"
    file.parent.mkdir(parents=True)
    file.write_text("import time\nimport pytest\ntime.sleep(1)\n")
    assert check(tmp_path, tmp_path, write=True) == 0
    assert check(tmp_path, tmp_path) == 0

    file.write_text("import time\nimport pytest\ntime.sleep(1)\ntime.sleep(2)\n")
    assert check(tmp_path, tmp_path) == 1

    file.write_text("import time\nimport pytest\ntime.sleep(1)\npytest.skip()\n")
    assert check(tmp_path, tmp_path) == 1

    file.write_text("import pytest\npytest.skip()\n")
    assert check(tmp_path, tmp_path) == 1


def test_python_format_reasons_need_fixed_text() -> None:
    source = """
pytest.skip("Requires {}".format(service))
pytest.skip("{}".format(reason))
pytest.skip("{0:>10}".format(reason))
pytest.skip("missing {".format(reason))
pytest.skip(get_reason())
"""
    assert list(python_findings(source)) == [
        (2, "skip", True),
        (3, "skip", False),
        (4, "skip", False),
        (5, "skip", False),
        (6, "skip", False),
    ]
