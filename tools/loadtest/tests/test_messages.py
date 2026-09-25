"""Tests for the question corpus that drives search load.

The corpus lives in its own module, so this needs neither locust nor a running
Onyx. The corpus properties matter for measurement: too few or too similar
questions turn every search into an index cache hit.
"""

from __future__ import annotations

import pytest
from onyx_client import messages as corpus


def test_corpus_is_large_and_unique() -> None:
    messages = corpus.DEFAULT_MESSAGES
    assert len(messages) >= 40
    assert len(set(messages)) == len(messages)


def test_corpus_varies_in_length() -> None:
    # A corpus of same-shaped questions clusters in the embedding space and
    # under-samples real query traffic.
    lengths = [len(m) for m in corpus.DEFAULT_MESSAGES]
    assert min(lengths) <= 40, "no short keyword-style queries"
    assert max(lengths) >= 120, "no long multi-clause queries"


def test_messages_file_overrides_corpus(tmp_path, monkeypatch) -> None:
    path = tmp_path / "questions.txt"
    path.write_text("first question\n\n  second question  \n", encoding="utf-8")
    monkeypatch.setenv("ONYX_MESSAGES_FILE", str(path))

    assert corpus.load_messages() == ["first question", "second question"]


def test_empty_messages_file_is_an_error(tmp_path, monkeypatch) -> None:
    path = tmp_path / "empty.txt"
    path.write_text("\n\n", encoding="utf-8")
    monkeypatch.setenv("ONYX_MESSAGES_FILE", str(path))

    with pytest.raises(RuntimeError):
        corpus.load_messages()


def test_default_corpus_used_without_override(monkeypatch) -> None:
    monkeypatch.delenv("ONYX_MESSAGES_FILE", raising=False)
    assert corpus.load_messages() == corpus.DEFAULT_MESSAGES
