"""Tenant-scoped persistence for the native memory capability."""

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from uuid import UUID

from pydantic_ai import ModelRetry
from pydantic_ai_harness.memory import (
    MemoryConflictError,
    MemoryFile,
    MemoryMutation,
    MemoryOperation,
    MemoryOperationConflictError,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.memory import MAX_MEMORIES_PER_USER
from onyx.db.models import Memory, MemoryFileMetadata, MemoryOperationReceipt, User
from shared_configs.contextvars import get_current_incognito_record_mode


@dataclass(frozen=True)
class MemoryChange:
    memory_id: int
    content: str
    existed: bool
    deleted: bool


def _version(row: Memory) -> str:
    return hashlib.sha256(
        f"{row.id}:{row.updated_at}:{row.memory_text}".encode()
    ).hexdigest()


class UserMemoryStore:
    """Store notebook files in the same rows that the personalization UI edits."""

    def __init__(
        self,
        *,
        tenant_id: str,
        user_id: UUID,
        writable: bool,
        conversation_id: UUID | None = None,
        message_id: int | None = None,
        on_change: Callable[[MemoryChange], None] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.writable = writable
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.on_change = on_change
        self.scope = f"{tenant_id}/{user_id}/main"

    def _authorize(self, write: bool = False) -> None:
        if get_current_incognito_record_mode() is not None:
            raise ModelRetry("Memory is unavailable in incognito chats.")
        if write and not self.writable:
            raise ModelRetry("The user disabled memory changes.")

    def _relative(self, path: str) -> str:
        prefix = f"{self.scope}/"
        if not path.startswith(prefix):
            raise ValueError("Memory path is outside the authorized user scope")
        relative = path[len(prefix) :]
        if (
            not relative
            or len(relative) > 1024
            or any(part in ("", ".", "..") for part in relative.split("/"))
            or "\\" in relative
            or "\x00" in relative
        ):
            raise ValueError("Invalid memory path")
        return relative

    def _rows(self, session: Session) -> list[tuple[Memory, str]]:
        rows = session.execute(
            select(Memory, MemoryFileMetadata.path)
            .outerjoin(MemoryFileMetadata, MemoryFileMetadata.memory_id == Memory.id)
            .where(Memory.user_id == self.user_id)
            .order_by(Memory.id.asc())
        ).all()
        return [(row, path or f"memories/{row.id}.md") for row, path in rows]

    def _receipt(
        self, session: Session, operation: MemoryOperation
    ) -> MemoryMutation | None:
        receipt = session.get(MemoryOperationReceipt, (self.user_id, operation.id))
        if receipt is None:
            return None
        if receipt.fingerprint != operation.fingerprint:
            raise MemoryOperationConflictError("Memory operation arguments changed")
        return MemoryMutation(
            version=receipt.version, replayed=True, existed=receipt.existed
        )

    async def read(self, path: str, *, max_chars: int) -> MemoryFile | None:
        self._authorize()
        relative = self._relative(path)

        def read() -> MemoryFile | None:
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                rows = self._rows(session)
                if relative == "MEMORY.md":
                    if not rows:
                        return None
                    content = "\n\n".join(
                        f"### {name}\n{row.memory_text}" for row, name in rows
                    )
                    version = hashlib.sha256(
                        "".join(_version(row) for row, _ in rows).encode()
                    ).hexdigest()
                    return MemoryFile(
                        content=content[:max_chars],
                        version=version,
                        operation_id=None,
                        truncated=len(content) > max_chars,
                    )
                for row, name in rows:
                    if name == relative:
                        return MemoryFile(
                            content=row.memory_text[:max_chars],
                            version=_version(row),
                            operation_id=None,
                            truncated=len(row.memory_text) > max_chars,
                        )
                return None

        return await asyncio.to_thread(read)

    async def list_paths(self, prefix: str = "", *, limit: int) -> list[str]:
        self._authorize()
        if (
            prefix
            and prefix != f"{self.scope}/"
            and not prefix.startswith(f"{self.scope}/")
        ):
            raise ValueError("Memory prefix is outside the authorized user scope")

        def paths() -> list[str]:
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                names = [f"{self.scope}/{name}" for _, name in self._rows(session)]
                return sorted(name for name in names if name.startswith(prefix))[:limit]

        return await asyncio.to_thread(paths)

    async def get_operation(self, operation: MemoryOperation) -> MemoryMutation | None:
        self._authorize()

        def get() -> MemoryMutation | None:
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                return self._receipt(session, operation)

        return await asyncio.to_thread(get)

    async def write(
        self,
        path: str,
        content: str,
        *,
        expected_version: str | None,
        operation: MemoryOperation | None = None,
    ) -> MemoryMutation:
        return await self._mutate(path, content, expected_version, operation)

    async def delete(
        self,
        path: str,
        *,
        expected_version: str | None,
        operation: MemoryOperation | None = None,
    ) -> MemoryMutation:
        return await self._mutate(path, None, expected_version, operation)

    async def _mutate(
        self,
        path: str,
        content: str | None,
        expected_version: str | None,
        operation: MemoryOperation | None,
    ) -> MemoryMutation:
        self._authorize(write=True)
        relative = self._relative(path)
        if relative == "MEMORY.md":
            raise ModelRetry(
                "MEMORY.md is the automatic index. Write a named file, such as preferences.md, or update a listed file."
            )

        cancelled = Event()

        def check_cancelled() -> None:
            if cancelled.is_set():
                raise asyncio.CancelledError()

        def mutate() -> tuple[MemoryMutation, MemoryChange | None]:
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                enabled = session.scalar(
                    select(User.enable_memory_tool)
                    .where(User.id == self.user_id)  # ty: ignore[invalid-argument-type]
                    .with_for_update()
                )
                check_cancelled()
                if enabled is None:
                    raise ValueError("Memory owner no longer exists")
                if not enabled:
                    raise ModelRetry("The user disabled memory changes.")
                if (
                    operation
                    and (receipt := self._receipt(session, operation)) is not None
                ):
                    return receipt, None
                rows = self._rows(session)
                row = next((memory for memory, name in rows if name == relative), None)
                if row is not None:
                    # UI mutations take the same user lock before editing rows.
                    session.refresh(row, with_for_update=True)
                current_version = _version(row) if row else None
                if current_version != expected_version:
                    raise MemoryConflictError("Memory changed since it was read")
                existed = row is not None
                change = None
                version = None
                if content is None:
                    if row is not None:
                        change = MemoryChange(row.id, row.memory_text, True, True)
                        session.execute(
                            delete(Memory).where(
                                Memory.id == row.id, Memory.user_id == self.user_id
                            )
                        )
                else:
                    if row is None:
                        if len(rows) >= MAX_MEMORIES_PER_USER:
                            session.execute(
                                delete(Memory).where(
                                    Memory.id == rows[0][0].id,
                                    Memory.user_id == self.user_id,
                                )
                            )
                            session.flush()
                        row = Memory(
                            user_id=self.user_id,
                            memory_text=content,
                            conversation_id=self.conversation_id,
                            message_id=self.message_id,
                        )
                        session.add(row)
                        session.flush()
                        session.add(
                            MemoryFileMetadata(
                                memory_id=row.id, user_id=self.user_id, path=relative
                            )
                        )
                    else:
                        row.memory_text = content
                        row.conversation_id = self.conversation_id
                        row.message_id = self.message_id
                    session.flush()
                    session.refresh(row)
                    version = _version(row)
                    change = MemoryChange(row.id, content, existed, False)
                mutation = MemoryMutation(
                    version=version, replayed=False, existed=existed
                )
                if operation is not None:
                    session.add(
                        MemoryOperationReceipt(
                            user_id=self.user_id,
                            operation_id=operation.id,
                            fingerprint=operation.fingerprint,
                            version=version,
                            existed=existed,
                        )
                    )
                check_cancelled()
                session.commit()
                return mutation, change

        try:
            mutation, change = await asyncio.to_thread(mutate)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        if change is not None and self.on_change:
            self.on_change(change)
        return mutation
