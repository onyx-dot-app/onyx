"""External-dependency-unit tests for chat history compression.

Reproduces (against real Postgres + cache backend) the failure mode where a
session's summaries were orphaned by message-tree forks: any regenerate, retry,
or concurrent send re-points ``latest_child_message_id``, and summaries matched
on ``parent_message_id`` fell off the mainline. Affected sessions re-summarized
their entire history at the end of every turn and their prompts were never
truncated.

Run with:
    python -m dotenv -f .vscode/.env run -- pytest \
        backend/tests/external_dependency_unit/chat/test_compression_fork_resilience.py
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_utils import create_chat_history_chain
from onyx.chat.compression import calculate_effective_history_tokens
from onyx.chat.compression import compress_chat_history
from onyx.chat.compression import COMPRESSION_LOCK_TIMEOUT_SECONDS
from onyx.chat.compression import CompressionParams
from onyx.chat.compression import find_summary_for_branch
from onyx.chat.compression import get_compression_params
from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatMessage
from onyx.db.models import User
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def test_user(db_session: Session) -> User:
    return create_test_user(db_session, "compression_fork")


@pytest.fixture
def chat_session_id(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001 — keeps tenant contextvar set for the test
    test_user: User,
) -> Generator[UUID, None, None]:
    session = create_chat_session(
        db_session=db_session,
        description="compression fork test",
        user_id=test_user.id,
        persona_id=None,
    )
    yield session.id


def _add_turns(
    db_session: Session,
    chat_session_id: UUID,
    parent: ChatMessage,
    num_turns: int,
    tokens_per_message: int = 500,
    label: str = "turn",
) -> ChatMessage:
    """Append ``num_turns`` USER/ASSISTANT exchanges after ``parent``."""
    tip = parent
    for i in range(num_turns):
        tip = create_new_chat_message(
            chat_session_id=chat_session_id,
            parent_message=tip,
            message=f"{label} user message {i}",
            token_count=tokens_per_message,
            message_type=MessageType.USER,
            db_session=db_session,
        )
        tip = create_new_chat_message(
            chat_session_id=chat_session_id,
            parent_message=tip,
            message=f"{label} assistant message {i}",
            token_count=tokens_per_message,
            message_type=MessageType.ASSISTANT,
            db_session=db_session,
        )
    return tip


def _compress(
    db_session: Session,
    chat_session_id: UUID,
    summary_text: str = "canned summary",
    tokens_for_recent: int | None = None,
) -> tuple[int, int | None]:
    """Run compression with a patched summarization LLM call.

    Returns (messages_summarized, cutoff_id_of_applicable_summary_afterwards).
    """
    # Tests reuse one session; expire so relationship attributes
    # (latest_child_message) reflect prior commits, as in a fresh
    # per-request session.
    db_session.expire_all()
    history = create_chat_history_chain(
        chat_session_id=chat_session_id, db_session=db_session
    )
    total_tokens = sum(m.token_count or 0 for m in history)
    params = CompressionParams(
        should_compress=True,
        tokens_for_recent=(
            tokens_for_recent
            if tokens_for_recent is not None
            else int(total_tokens * 0.2)
        ),
    )

    with patch(
        "onyx.chat.compression.generate_summary", return_value=summary_text
    ) as mock_generate:
        result = compress_chat_history(
            chat_history=history,
            llm=MagicMock(),
            compression_params=params,
        )
        llm_called = mock_generate.call_count

    db_session.expire_all()
    history = create_chat_history_chain(
        chat_session_id=chat_session_id, db_session=db_session
    )
    summary = find_summary_for_branch(db_session, history)
    cutoff = summary.last_summarized_message_id if summary else None
    assert result.error is None
    assert llm_called <= 1
    return result.messages_summarized, cutoff


class TestCompressionForkResilience:
    def test_summary_survives_regeneration_fork(
        self, db_session: Session, chat_session_id: UUID
    ) -> None:
        """A regenerate (sibling message) must not orphan existing summaries."""
        root = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
        tip = _add_turns(db_session, chat_session_id, root, num_turns=10)

        summarized_1, cutoff_1 = _compress(db_session, chat_session_id)
        assert summarized_1 > 0
        assert cutoff_1 is not None

        # Simulate a regenerate: attach a sibling at the tip's parent. This
        # re-points latest_child_message_id, moving the mainline off the
        # branch the summary's parent pointer references.
        parent_of_tip = db_session.get(ChatMessage, tip.parent_message_id)
        assert parent_of_tip is not None
        regen_tip = create_new_chat_message(
            chat_session_id=chat_session_id,
            parent_message=parent_of_tip,
            message="regenerated assistant message",
            token_count=500,
            message_type=MessageType.ASSISTANT,
            db_session=db_session,
        )

        # The test reuses one session; expire so relationship attributes
        # (latest_child_message) reflect the just-committed fork, as they
        # would in a fresh per-request session.
        db_session.expire_all()
        history = create_chat_history_chain(
            chat_session_id=chat_session_id, db_session=db_session
        )
        history_ids = {m.id for m in history}
        assert regen_tip.id in history_ids, "fork should be on the mainline"
        assert tip.id not in history_ids, "old tip should be off the mainline"

        summary = find_summary_for_branch(db_session, history)
        assert summary is not None, "summary must survive the fork"
        assert summary.last_summarized_message_id == cutoff_1

    def test_cutoff_advances_instead_of_full_recompression(
        self, db_session: Session, chat_session_id: UUID
    ) -> None:
        """Subsequent compressions must be progressive, not from scratch."""
        root = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
        tip = _add_turns(db_session, chat_session_id, root, num_turns=10)

        summarized_1, cutoff_1 = _compress(db_session, chat_session_id)
        assert summarized_1 > 0
        assert cutoff_1 is not None

        # Fork (regenerate), then continue the conversation past the fork.
        parent_of_tip = db_session.get(ChatMessage, tip.parent_message_id)
        assert parent_of_tip is not None
        _add_turns(
            db_session,
            chat_session_id,
            parent_of_tip,
            num_turns=10,
            label="post-fork",
        )

        summarized_2, cutoff_2 = _compress(db_session, chat_session_id)

        assert summarized_2 > 0
        assert summarized_2 < summarized_1 + 10, (
            "second compression must only cover post-cutoff messages, "
            "not re-summarize the whole session"
        )
        assert cutoff_2 is not None and cutoff_1 is not None
        assert cutoff_2 > cutoff_1, "cutoff must advance"

    def test_tiny_tail_skips_llm_call(
        self, db_session: Session, chat_session_id: UUID
    ) -> None:
        """Re-running compression with a trivial new tail must not call the LLM."""
        root = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
        tip = _add_turns(db_session, chat_session_id, root, num_turns=10)

        # Compress with a tiny recent budget so the cutoff lands at the very
        # end of the history — everything is summarized.
        summarized_1, _ = _compress(db_session, chat_session_id, tokens_for_recent=100)
        assert summarized_1 > 0

        # One small follow-up exchange (100 tokens total, below
        # MIN_TOKENS_TO_COMPRESS) — not worth an LLM round-trip.
        _add_turns(
            db_session,
            chat_session_id,
            tip,
            num_turns=1,
            tokens_per_message=50,
            label="tiny",
        )

        db_session.expire_all()
        history = create_chat_history_chain(
            chat_session_id=chat_session_id, db_session=db_session
        )
        params = CompressionParams(should_compress=True, tokens_for_recent=0)
        with patch(
            "onyx.chat.compression.generate_summary", return_value="unused"
        ) as mock_generate:
            result = compress_chat_history(
                chat_history=history,
                llm=MagicMock(),
                compression_params=params,
            )

        assert result.summary_created is False
        assert mock_generate.call_count == 0

    def test_concurrent_compression_skipped_via_lock(
        self, db_session: Session, chat_session_id: UUID
    ) -> None:
        """A second compression for the same session must no-op while one is in flight."""
        root = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
        _add_turns(db_session, chat_session_id, root, num_turns=10)

        db_session.expire_all()
        history = create_chat_history_chain(
            chat_session_id=chat_session_id, db_session=db_session
        )
        params = CompressionParams(should_compress=True, tokens_for_recent=1000)

        lock = get_cache_backend().lock(
            f"chat_compression_lock:{chat_session_id}",
            timeout=COMPRESSION_LOCK_TIMEOUT_SECONDS,
        )
        assert lock.acquire(blocking=False)
        try:
            with patch(
                "onyx.chat.compression.generate_summary", return_value="unused"
            ) as mock_generate:
                result = compress_chat_history(
                    chat_history=history,
                    llm=MagicMock(),
                    compression_params=params,
                )
        finally:
            lock.release()

        assert result.summary_created is False
        assert mock_generate.call_count == 0

    def test_effective_tokens_prevent_per_turn_retrigger(
        self, db_session: Session, chat_session_id: UUID
    ) -> None:
        """Once compressed, the trigger must consider the prompt-effective size."""
        root = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
        _add_turns(db_session, chat_session_id, root, num_turns=10)

        summarized, _ = _compress(db_session, chat_session_id)
        assert summarized > 0

        db_session.expire_all()
        history = create_chat_history_chain(
            chat_session_id=chat_session_id, db_session=db_session
        )
        summary = find_summary_for_branch(db_session, history)
        assert summary is not None

        raw_tokens = sum(m.token_count or 0 for m in history)
        effective_tokens = calculate_effective_history_tokens(history, summary)
        assert effective_tokens < raw_tokens

        # With the raw total the old trigger would fire again immediately;
        # with the effective total it must not.
        max_input = int(raw_tokens / 0.75) - 100  # threshold just under raw
        assert get_compression_params(
            max_input_tokens=max_input,
            current_history_tokens=raw_tokens,
            reserved_tokens=0,
        ).should_compress
        assert not get_compression_params(
            max_input_tokens=max_input,
            current_history_tokens=effective_tokens,
            reserved_tokens=0,
        ).should_compress

    def test_cache_backend_failure_does_not_break_compression(
        self, db_session: Session, chat_session_id: UUID
    ) -> None:
        """Compression is best-effort: a cache outage must not propagate —
        it degrades to running without the concurrency lock."""
        root = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
        _add_turns(db_session, chat_session_id, root, num_turns=10)

        db_session.expire_all()
        history = create_chat_history_chain(
            chat_session_id=chat_session_id, db_session=db_session
        )
        params = CompressionParams(should_compress=True, tokens_for_recent=2000)

        with (
            patch(
                "onyx.chat.compression.get_cache_backend",
                side_effect=ConnectionError("cache backend down"),
            ),
            patch(
                "onyx.chat.compression.generate_summary",
                return_value="canned summary",
            ) as mock_generate,
        ):
            result = compress_chat_history(
                chat_history=history,
                llm=MagicMock(),
                compression_params=params,
            )

        assert result.error is None
        assert result.summary_created is True
        assert mock_generate.call_count == 1
