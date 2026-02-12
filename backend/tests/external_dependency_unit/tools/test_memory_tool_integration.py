"""Tests for MemoryTool integration: registration, construction, and DB persistence."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.memory import add_memory
from onyx.db.memory import get_memories
from onyx.db.memory import MAX_MEMORIES_PER_USER
from onyx.db.memory import update_memory_at_index
from onyx.db.models import Memory
from onyx.db.models import User
from onyx.tools.tool_implementations.memory.models import MemoryToolResponse
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture()
def test_user(db_session: Session):  # type: ignore
    """Create a test user with use_memories enabled."""
    user = create_test_user(db_session, "memory_test")
    user.use_memories = True
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def test_user_no_memories(db_session: Session):  # type: ignore
    """Create a test user with use_memories disabled."""
    user = create_test_user(db_session, "memory_test_off")
    user.use_memories = False
    db_session.commit()
    db_session.refresh(user)
    return user


class TestAddMemory:
    def test_add_memory_creates_row(self, db_session: Session, test_user: User) -> None:
        """Verify that add_memory inserts a new Memory row."""
        user_id = test_user.id
        memory = add_memory(
            user_id=user_id,
            memory_text="User prefers dark mode",
            db_session=db_session,
        )

        assert memory.id is not None
        assert memory.user_id == user_id
        assert memory.memory_text == "User prefers dark mode"

        # Verify it persists
        fetched = db_session.get(Memory, memory.id)
        assert fetched is not None
        assert fetched.memory_text == "User prefers dark mode"

    def test_add_multiple_memories(self, db_session: Session, test_user: User) -> None:
        """Verify that multiple memories can be added for the same user."""
        user_id = test_user.id
        m1 = add_memory(
            user_id=user_id,
            memory_text="Favorite color is blue",
            db_session=db_session,
        )
        m2 = add_memory(
            user_id=user_id,
            memory_text="Works in engineering",
            db_session=db_session,
        )

        assert m1.id != m2.id
        assert m1.memory_text == "Favorite color is blue"
        assert m2.memory_text == "Works in engineering"


class TestUpdateMemoryAtIndex:
    def test_update_memory_at_valid_index(
        self, db_session: Session, test_user: User
    ) -> None:
        """Verify that update_memory_at_index updates the correct row."""
        user_id = test_user.id
        add_memory(user_id=user_id, memory_text="Memory 0", db_session=db_session)
        add_memory(user_id=user_id, memory_text="Memory 1", db_session=db_session)
        add_memory(user_id=user_id, memory_text="Memory 2", db_session=db_session)

        updated = update_memory_at_index(
            user_id=user_id,
            index=1,
            new_text="Updated Memory 1",
            db_session=db_session,
        )

        assert updated is not None
        assert updated.memory_text == "Updated Memory 1"

    def test_update_memory_at_out_of_range_index(
        self, db_session: Session, test_user: User
    ) -> None:
        """Verify that out-of-range index returns None."""
        user_id = test_user.id
        add_memory(user_id=user_id, memory_text="Only memory", db_session=db_session)

        result = update_memory_at_index(
            user_id=user_id,
            index=5,
            new_text="Should not update",
            db_session=db_session,
        )

        assert result is None

    def test_update_memory_at_negative_index(
        self, db_session: Session, test_user: User
    ) -> None:
        """Verify that negative index returns None."""
        user_id = test_user.id
        add_memory(user_id=user_id, memory_text="Only memory", db_session=db_session)

        result = update_memory_at_index(
            user_id=user_id,
            index=-1,
            new_text="Should not update",
            db_session=db_session,
        )

        assert result is None


class TestMemoryToolResponse:
    def test_response_with_add(self) -> None:
        """Verify MemoryToolResponse correctly carries add (index_to_replace=None)."""
        response = MemoryToolResponse(
            memory_text="User likes Python",
            index_to_replace=None,
        )
        assert response.memory_text == "User likes Python"
        assert response.index_to_replace is None

    def test_response_with_update(self) -> None:
        """Verify MemoryToolResponse correctly carries update (index_to_replace=int)."""
        response = MemoryToolResponse(
            memory_text="User likes TypeScript",
            index_to_replace=2,
        )
        assert response.memory_text == "User likes TypeScript"
        assert response.index_to_replace == 2


class TestMemoryCap:
    def test_add_memory_evicts_oldest_when_at_cap(
        self, db_session: Session, test_user: User
    ) -> None:
        """When the user has MAX_MEMORIES_PER_USER memories, adding a new one
        should delete the oldest (lowest id) and keep the total at the cap."""
        user_id = test_user.id

        # Fill up to the cap
        for i in range(MAX_MEMORIES_PER_USER):
            add_memory(
                user_id=user_id,
                memory_text=f"Memory {i}",
                db_session=db_session,
            )

        rows_before = db_session.scalars(
            Memory.__table__.select().where(Memory.user_id == user_id)
        ).all()
        assert len(rows_before) == MAX_MEMORIES_PER_USER

        # Add one more — should evict the oldest
        new_memory = add_memory(
            user_id=user_id,
            memory_text="New memory after cap",
            db_session=db_session,
        )

        rows_after = db_session.scalars(
            select(Memory).where(Memory.user_id == user_id).order_by(Memory.id.asc())
        ).all()

        assert len(rows_after) == MAX_MEMORIES_PER_USER
        # Oldest ("Memory 0") should be gone; "Memory 1" is now the oldest
        assert rows_after[0].memory_text == "Memory 1"
        # Newest should be the one we just added
        assert rows_after[-1].id == new_memory.id
        assert rows_after[-1].memory_text == "New memory after cap"


class TestGetMemoriesWithUserId:
    def test_get_memories_populates_user_id(
        self, db_session: Session, test_user: User
    ) -> None:
        """Verify that get_memories populates user_id on the returned context."""
        context = get_memories(test_user, db_session)
        assert context.user_id == test_user.id

    def test_get_memories_disabled_still_populates_user_id(
        self, db_session: Session, test_user_no_memories: User
    ) -> None:
        """Verify that get_memories with use_memories=False still returns a
        fully populated context (user_id, user_info, memories). The
        use_memories flag only controls whether memories are injected into
        the system prompt, not whether the context is fetched."""
        # Add a memory for this user so we can verify it's fetched
        add_memory(
            user_id=test_user_no_memories.id,
            memory_text="Should still be fetched",
            db_session=db_session,
        )

        context = get_memories(test_user_no_memories, db_session)
        assert context.user_id == test_user_no_memories.id
        assert context.user_info.email == test_user_no_memories.email
        assert len(context.memories) == 1
        assert context.memories[0] == "Should still be fetched"

    def test_get_memories_disabled_persistence_works(
        self, db_session: Session, test_user_no_memories: User
    ) -> None:
        """Verify that add_memory and update_memory_at_index work correctly
        when use_memories=False, since the memory tool should still persist."""
        user_id = test_user_no_memories.id

        # Add a memory
        memory = add_memory(
            user_id=user_id,
            memory_text="Memory with use_memories off",
            db_session=db_session,
        )
        assert memory.memory_text == "Memory with use_memories off"

        # Update that memory
        updated = update_memory_at_index(
            user_id=user_id,
            index=0,
            new_text="Updated memory with use_memories off",
            db_session=db_session,
        )
        assert updated is not None
        assert updated.memory_text == "Updated memory with use_memories off"

        # Verify get_memories returns the updated memory
        context = get_memories(test_user_no_memories, db_session)
        assert len(context.memories) == 1
        assert context.memories[0] == "Updated memory with use_memories off"
