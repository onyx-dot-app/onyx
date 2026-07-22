from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

from onyx.llm.interfaces import LLM


@contextmanager
def noop_span() -> Iterator[MagicMock]:
    yield MagicMock()


def make_llm(invoke: MagicMock) -> LLM:
    llm = MagicMock(spec=LLM)
    llm.invoke = invoke
    return llm
