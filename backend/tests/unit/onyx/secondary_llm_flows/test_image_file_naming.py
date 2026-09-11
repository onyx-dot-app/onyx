from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.image_file_naming import generate_image_file_stem


@contextmanager
def _noop_span() -> Iterator[MagicMock]:
    yield MagicMock()


def _make_llm(invoke: MagicMock) -> LLM:
    llm = MagicMock(spec=LLM)
    llm.invoke = invoke
    return llm


def test_generate_image_file_stem_without_llm_slugifies_prompt() -> None:
    assert generate_image_file_stem("Sweet cat on a bike", None) == (
        "sweet-cat-on-a-bike"
    )


@patch("onyx.secondary_llm_flows.image_file_naming.record_llm_response")
@patch(
    "onyx.secondary_llm_flows.image_file_naming.llm_generation_span",
    return_value=_noop_span(),
)
@patch(
    "onyx.secondary_llm_flows.image_file_naming.llm_response_to_string",
    return_value="Sweet Cat on a Bike",
)
def test_generate_image_file_stem_uses_llm_name(
    _to_string: MagicMock, _span: MagicMock, _record: MagicMock
) -> None:
    llm = _make_llm(MagicMock())
    assert generate_image_file_stem("draw a cat riding a bicycle", llm) == (
        "sweet-cat-on-a-bike"
    )


@patch("onyx.secondary_llm_flows.image_file_naming.record_llm_response")
@patch(
    "onyx.secondary_llm_flows.image_file_naming.llm_generation_span",
    return_value=_noop_span(),
)
def test_generate_image_file_stem_falls_back_when_llm_fails(
    _span: MagicMock, _record: MagicMock
) -> None:
    llm = _make_llm(MagicMock(side_effect=RuntimeError("unavailable")))
    assert generate_image_file_stem("Sweet cat on a bike", llm) == (
        "sweet-cat-on-a-bike"
    )
