"""The response_model check flags the keyword on route decorators and
`add_api_route`, leaves `response_model=None` and non-route calls alone,
accepts an allow marker only with a reason, and holds each file to its
baseline count."""

from pathlib import Path

import pytest
from lint import check_no_response_model

_HANDLER = "def handler() -> Model:\n    return Model()\n"


@pytest.mark.parametrize(
    "decorator",
    [
        '@router.post("/eval_run", response_model=EvalRunAck)',
        '@admin_router.get("", response_model=list[EmbeddingModelDetail])',
        '@router.patch("/{project_id}", response_model=UserProjectSnapshot, tags=PUBLIC_API_TAGS)',
        '@scim_router.put("/Users/{user_id}", response_model=ScimUserResource)',
        '@router.delete("/{session_id}", response_model=StatusResponse[int])',
        '@router.api_route("/token", methods=["POST", "OPTIONS"], response_model=Token)',
        '@app.get("/health", response_model=StatusResponse)',
        '@router.get("/x", response_model=Model)  # no-response-model: allow',
        '@router.get("/x", response_model=Model)  # no-response-model: allow -',
        '@router.get("/x", response_model=Model, description="no-response-model: allow legacy shape")',
    ],
)
def test_response_model_on_a_route_decorator_is_flagged(decorator: str) -> None:
    source = f"{decorator}\n{_HANDLER}"
    assert [
        line for line, _ in check_no_response_model.find_response_models(source)
    ] == [1]


@pytest.mark.parametrize(
    "decorator",
    [
        '@router.post("/eval_run")',
        '@router.get("/file/{file_id}", tags=PUBLIC_API_TAGS)',
        '@scim_router.get("/Users", response_model=None)',
        '@scim_router.post("/Users", status_code=201, response_model=None)',
        '@router.api_route("/metadata", methods=["GET", "OPTIONS"])',
        '@router.get("/x", response_model=Model)  # no-response-model: allow the handler also returns a Response',
        "@lru_cache(response_model=Model)",
    ],
)
def test_clean_decorators_pass(decorator: str) -> None:
    source = f"{decorator}\n{_HANDLER}"
    assert check_no_response_model.find_response_models(source) == []


def test_keyword_line_is_reported_in_a_multi_line_decorator() -> None:
    source = (
        "@router.post(\n"
        '    "/send-chat-message",\n'
        "    response_model=ChatFullResponse,\n"
        "    tags=PUBLIC_API_TAGS,\n"
        ")\n" + _HANDLER
    )
    assert check_no_response_model.find_response_models(source) == [
        (3, "response_model= on a route")
    ]


@pytest.mark.parametrize(
    "marked",
    [
        "    response_model=ChatFullResponse,  # no-response-model: allow union with a Response\n",
        "    # no-response-model: allow the handler returns dicts\n"
        "    response_model=list[ArtifactResponse],\n",
    ],
)
def test_marker_inside_a_multi_line_decorator_exempts_it(marked: str) -> None:
    source = f'@router.get(\n    "/x",\n{marked})\n{_HANDLER}'
    assert check_no_response_model.find_response_models(source) == []


def test_marker_without_a_reason_names_the_problem() -> None:
    source = f'@router.get("/x", response_model=Model)  # no-response-model: allow\n{_HANDLER}'
    assert check_no_response_model.find_response_models(source) == [
        (1, "allow marker without a reason")
    ]


def test_marker_exempts_only_its_own_route() -> None:
    source = (
        '@router.get("/a", response_model=Model)  # no-response-model: allow legacy shape\n'
        + _HANDLER
        + '@router.get("/b", response_model=Model)\n'
        + _HANDLER
    )
    assert [
        line for line, _ in check_no_response_model.find_response_models(source)
    ] == [4]


def test_add_api_route_is_flagged_but_other_calls_are_not() -> None:
    source = (
        'router.add_api_route("/hook", endpoint, methods=["POST"], response_model=Ack)\n'
        'router.add_api_route("/hook", endpoint, methods=["POST"])\n'
        'client.get("/x", response_model=Model)\n'
        "spec = HookSpec(response_model=DocumentPushResponse)\n"
        "response_model = QueryProcessingResponse\n"
    )
    assert [
        line for line, _ in check_no_response_model.find_response_models(source)
    ] == [1]


_BAD = f'@router.get("/x", response_model=Model)\n{_HANDLER}'
_GOOD = f'@router.get("/x")\n{_HANDLER}'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A repo root with one clean route file and one file with two uses."""
    server = tmp_path / "backend" / "onyx" / "server"
    server.mkdir(parents=True)
    (server / "ok.py").write_text(_GOOD, encoding="utf-8")
    (server / "legacy.py").write_text(_BAD + _BAD, encoding="utf-8")
    return tmp_path


def test_non_ascii_source_is_read_as_utf8(root: Path) -> None:
    path = root / "backend" / "onyx" / "server" / "ok.py"
    path.write_text(f'NAME = "caf\u00e9 \u65e5\u672c"\n{_BAD}', encoding="utf-8")
    assert check_no_response_model.scan(root)["backend/onyx/server/ok.py"] == [
        (2, "response_model= on a route")
    ]


def test_baseline_round_trip_passes(root: Path) -> None:
    baseline = root / "baseline.txt"
    check_no_response_model.write_baseline(baseline, check_no_response_model.scan(root))
    assert check_no_response_model.read_baseline(baseline) == {
        "backend/onyx/server/legacy.py": 2
    }
    assert check_no_response_model.check(root, baseline) == 0


def test_new_use_in_a_clean_file_fails_naming_the_line_and_the_fix(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = root / "baseline.txt"
    check_no_response_model.write_baseline(baseline, check_no_response_model.scan(root))
    (root / "backend" / "onyx" / "server" / "ok.py").write_text(_BAD, encoding="utf-8")
    assert check_no_response_model.check(root, baseline) == 1
    out = capsys.readouterr().out
    assert "backend/onyx/server/ok.py:1" in out
    assert "return annotation" in out
    assert check_no_response_model.ALLOW_MARKER in out


def test_new_use_in_a_baselined_file_fails(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = root / "baseline.txt"
    check_no_response_model.write_baseline(baseline, check_no_response_model.scan(root))
    (root / "backend" / "onyx" / "server" / "legacy.py").write_text(
        _BAD * 3, encoding="utf-8"
    )
    assert check_no_response_model.check(root, baseline) == 1
    assert "3 uses, the baseline allows 2" in capsys.readouterr().out


def test_removed_use_fails_until_the_baseline_is_regenerated(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = root / "baseline.txt"
    check_no_response_model.write_baseline(baseline, check_no_response_model.scan(root))
    (root / "backend" / "onyx" / "server" / "legacy.py").write_text(
        _BAD, encoding="utf-8"
    )
    assert check_no_response_model.check(root, baseline) == 1
    assert "--write-baseline" in capsys.readouterr().out
    check_no_response_model.write_baseline(baseline, check_no_response_model.scan(root))
    assert check_no_response_model.check(root, baseline) == 0


def test_missing_baseline_allows_nothing(root: Path) -> None:
    assert check_no_response_model.check(root, root / "absent.txt") == 1
