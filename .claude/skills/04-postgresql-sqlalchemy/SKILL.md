---
name: postgresql-sqlalchemy
description: SQLAlchemy ORM patterns, Alembic migrations, query optimization, and connection pooling for Onyx's PostgreSQL database. Use when working with database models, migrations, or optimizing queries.
---

# PostgreSQL & SQLAlchemy Skill for Onyx

## Overview

Onyx uses PostgreSQL for storing metadata, user data, connector configurations, and application state. This skill covers async SQLAlchemy patterns, Alembic migrations, query optimization, and RBAC schema design.

## Architecture Context

**Database Stack:**
- **Database**: PostgreSQL 14+
- **ORM**: SQLAlchemy 2.0 (async)
- **Migrations**: Alembic
- **Connection Management**: asyncpg driver
- **Location**: `backend/danswer/db/`

**Key Tables:**
- `users` - User accounts and authentication
- `documents` - Document metadata
- `document_chunks` - Indexed chunks
- `connectors` - Connector configurations
- `conversations` - Chat history
- `permissions` - Access control

## SQLAlchemy Models

### Model Definition Patterns

```python
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Table, Boolean, JSON, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs
from datetime import datetime
from typing import List, Optional

from danswer.db.base import Base

# Onyx model pattern: Use new SQLAlchemy 2.0 syntax
class User(AsyncAttrs, Base):
    """
    User model with modern SQLAlchemy 2.0 patterns.
    
    Onyx patterns:
    - Use Mapped[] for type hints
    - AsyncAttrs for async relationship loading
    - Timestamps for audit trail
    """
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # SSO fields
    oauth_provider: Mapped[Optional[str]] = mapped_column(String)
    oauth_id: Mapped[Optional[str]] = mapped_column(String)
    
    # User info
    full_name: Mapped[Optional[str]] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    # Relationships
    documents: Mapped[List["Document"]] = relationship(back_populates="user")
    connectors: Mapped[List["Connector"]] = relationship(back_populates="user")
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"

class Document(AsyncAttrs, Base):
    """Document metadata model."""
    __tablename__ = "documents"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    
    # Document info
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String)  # External ID
    url: Mapped[Optional[str]] = mapped_column(String)
    
    # Content metadata
    file_name: Mapped[Optional[str]] = mapped_column(String)
    mime_type: Mapped[Optional[str]] = mapped_column(String)
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Indexing status
    status: Mapped[str] = mapped_column(
        String,
        default="pending",
        index=True
    )  # pending, indexing, completed, failed
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="documents")
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan"
    )
    permissions: Mapped[List["DocumentPermission"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan"
    )

# Many-to-many association table
user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
    Column("group_id", String, ForeignKey("groups.id"), primary_key=True)
)

class Group(AsyncAttrs, Base):
    """User group for permissions."""
    __tablename__ = "groups"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    users: Mapped[List["User"]] = relationship(
        secondary=user_groups,
        backref="groups"
    )
```

### Composite Indexes and Constraints

```python
from sqlalchemy import Index, UniqueConstraint, CheckConstraint

class DocumentChunk(AsyncAttrs, Base):
    """
    Document chunk for vector search.
    
    Onyx optimization: Composite indexes for common queries
    """
    __tablename__ = "document_chunks"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Composite index for (document_id, chunk_index)
    __table_args__ = (
        Index("ix_document_chunks_doc_index", "document_id", "chunk_index"),
        UniqueConstraint("document_id", "chunk_index", name="uq_doc_chunk"),
    )

class Connector(AsyncAttrs, Base):
    """Connector configuration."""
    __tablename__ = "connectors"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    connector_type: Mapped[str] = mapped_column(String, nullable=False)
    
    # Encrypted credentials stored as JSON
    credentials_encrypted: Mapped[dict] = mapped_column(JSON)
    
    # Sync state
    last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sync_status: Mapped[str] = mapped_column(String, default="idle")
    
    __table_args__ = (
        Index("ix_connectors_user_type", "user_id", "connector_type"),
        CheckConstraint(
            "sync_status IN ('idle', 'running', 'failed', 'paused')",
            name="ck_sync_status"
        ),
    )
```

## Alembic Migrations

### Migration File Structure

```python
# alembic/versions/xxxx_add_document_permissions.py
"""Add document permissions table

Revision ID: xxxx
Revises: yyyy
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'xxxx'
down_revision = 'yyyy'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """
    Onyx migration pattern:
    - Create tables with proper indexes
    - Add foreign keys with cascades
    - Set default values
    """
    op.create_table(
        'document_permissions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('group_id', sa.String(), nullable=True),
        sa.Column('permission_type', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['document_id'],
            ['documents.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id']),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Add indexes
    op.create_index(
        'ix_document_permissions_doc_user',
        'document_permissions',
        ['document_id', 'user_id']
    )

def downgrade() -> None:
    """Rollback migration."""
    op.drop_index('ix_document_permissions_doc_user')
    op.drop_table('document_permissions')
```

### Data Migration Pattern

```python
"""Migrate existing data to new schema

Revision ID: xxxx
"""

def upgrade() -> None:
    """
    Onyx data migration pattern:
    - Use bulk operations for performance
    - Handle errors gracefully
    - Log progress
    """
    # Get connection
    conn = op.get_bind()
    
    # Bulk update in batches
    batch_size = 1000
    offset = 0
    
    while True:
        # Fetch batch
        result = conn.execute(
            sa.text("""
                SELECT id, old_field 
                FROM documents 
                WHERE new_field IS NULL
                LIMIT :limit OFFSET :offset
            """),
            {"limit": batch_size, "offset": offset}
        )
        
        rows = result.fetchall()
        if not rows:
            break
        
        # Transform and update
        updates = [
            {
                "doc_id": row.id,
                "new_value": transform_value(row.old_field)
            }
            for row in rows
        ]
        
        conn.execute(
            sa.text("""
                UPDATE documents
                SET new_field = :new_value
                WHERE id = :doc_id
            """),
            updates
        )
        
        offset += batch_size
```

## Query Patterns

### Async Query Execution

```python
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

async def get_user_with_documents(
    db: AsyncSession,
    user_id: str
) -> Optional[User]:
    """
    Fetch user with documents using eager loading.
    
    Onyx pattern: Use selectinload to avoid N+1 queries
    """
    stmt = (
        select(User)
        .options(selectinload(User.documents))
        .where(User.id == user_id)
    )
    
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def search_documents_by_user(
    db: AsyncSession,
    user_id: str,
    search_term: str,
    limit: int = 10
) -> List[Document]:
    """
    Search documents with filtering and pagination.
    
    Uses ILIKE for case-insensitive search
    """
    stmt = (
        select(Document)
        .where(
            Document.user_id == user_id,
            Document.title.ilike(f"%{search_term}%")
        )
        .order_by(Document.created_at.desc())
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    return result.scalars().all()
```

### Complex Joins

```python
async def get_user_accessible_documents(
    db: AsyncSession,
    user_id: str
) -> List[Document]:
    """
    Get documents user has access to via permissions.
    
    Onyx permission pattern:
    - Check direct ownership
    - Check user permissions
    - Check group permissions
    """
    # Subquery for user's groups
    user_groups_subq = (
        select(user_groups.c.group_id)
        .where(user_groups.c.user_id == user_id)
    ).scalar_subquery()
    
    stmt = (
        select(Document)
        .outerjoin(DocumentPermission)
        .where(
            sa.or_(
                # User owns document
                Document.user_id == user_id,
                # User has direct permission
                DocumentPermission.user_id == user_id,
                # User's group has permission
                DocumentPermission.group_id.in_(user_groups_subq)
            )
        )
        .distinct()
    )
    
    result = await db.execute(stmt)
    return result.scalars().all()
```

### Aggregations

```python
async def get_document_stats(
    db: AsyncSession,
    user_id: str
) -> dict:
    """
    Get document statistics for user.
    
    Onyx analytics pattern: Use func for aggregations
    """
    stmt = (
        select(
            func.count(Document.id).label("total_docs"),
            func.sum(Document.chunk_count).label("total_chunks"),
            func.avg(Document.file_size).label("avg_file_size"),
            func.count(
                sa.case((Document.status == "completed", 1))
            ).label("completed_docs")
        )
        .where(Document.user_id == user_id)
    )
    
    result = await db.execute(stmt)
    row = result.one()
    
    return {
        "total_documents": row.total_docs,
        "total_chunks": row.total_chunks or 0,
        "average_file_size": row.avg_file_size or 0,
        "completed_documents": row.completed_docs
    }
```

## Transaction Management

### Transaction Patterns

```python
async def create_document_with_chunks(
    db: AsyncSession,
    document_data: dict,
    chunks: List[dict]
) -> Document:
    """
    Create document and chunks in transaction.
    
    Onyx transaction pattern:
    - Manual commit for explicit control
    - Rollback on error
    """
    try:
        # Create document
        document = Document(**document_data)
        db.add(document)
        await db.flush()  # Get document.id without committing
        
        # Create chunks
        for i, chunk_data in enumerate(chunks):
            chunk = DocumentChunk(
                document_id=document.id,
                chunk_index=i,
                content=chunk_data["content"]
            )
            db.add(chunk)
        
        await db.commit()
        await db.refresh(document)
        
        return document
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create document: {e}")
        raise
```

### Nested Transactions with Savepoints

```python
async def batch_update_with_savepoints(
    db: AsyncSession,
    updates: List[dict]
):
    """
    Batch update with per-item savepoints.
    
    Allows partial success if some updates fail.
    """
    successful = []
    failed = []
    
    for update_data in updates:
        # Create savepoint
        async with db.begin_nested():
            try:
                stmt = (
                    update(Document)
                    .where(Document.id == update_data["id"])
                    .values(**update_data["values"])
                )
                await db.execute(stmt)
                successful.append(update_data["id"])
                
            except Exception as e:
                # Rollback to savepoint
                logger.error(f"Update failed for {update_data['id']}: {e}")
                failed.append(update_data["id"])
    
    # Commit outer transaction
    await db.commit()
    
    return {"successful": successful, "failed": failed}
```

## Performance Optimization

### Connection Pooling

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

def create_engine(database_url: str):
    """
    Create engine with optimized pool settings.
    
    Onyx pool configuration:
    - QueuePool for web workers
    - NullPool for background workers
    - Appropriate pool size for workload
    """
    return create_async_engine(
        database_url,
        echo=False,
        poolclass=QueuePool,
        pool_size=20,  # Max connections
        max_overflow=10,  # Extra connections when needed
        pool_pre_ping=True,  # Verify connections before use
        pool_recycle=3600,  # Recycle connections after 1 hour
    )

async def warm_up_connections():
    """Warm up connection pool on startup."""
    async with engine.connect() as conn:
        await conn.execute(sa.text("SELECT 1"))
```

### Query Optimization

```python
# ❌ Bad: N+1 query problem
async def get_documents_bad(db: AsyncSession):
    documents = await db.execute(select(Document))
    for doc in documents.scalars():
        # Triggers separate query for each document!
        await db.refresh(doc, ["user"])

# ✅ Good: Eager loading
async def get_documents_good(db: AsyncSession):
    stmt = select(Document).options(joinedload(Document.user))
    result = await db.execute(stmt)
    return result.unique().scalars().all()

# ✅ Good: Batch loading
async def get_users_for_documents(
    db: AsyncSession,
    document_ids: List[str]
) -> dict[str, User]:
    """Fetch users for multiple documents in one query."""
    stmt = (
        select(User)
        .join(Document)
        .where(Document.id.in_(document_ids))
    )
    
    result = await db.execute(stmt)
    users = result.scalars().all()
    
    # Map to document IDs
    user_map = {}
    for doc_id in document_ids:
        # ... mapping logic
    
    return user_map
```

### Bulk Operations

```python
from sqlalchemy.dialects.postgresql import insert

async def bulk_upsert_documents(
    db: AsyncSession,
    documents: List[dict]
):
    """
    Bulk upsert documents efficiently.
    
    Uses PostgreSQL ON CONFLICT for upsert
    """
    stmt = insert(Document).values(documents)
    
    # On conflict, update specific fields
    stmt = stmt.on_conflict_do_update(
        index_elements=['id'],
        set_={
            'title': stmt.excluded.title,
            'updated_at': datetime.utcnow()
        }
    )
    
    await db.execute(stmt)
    await db.commit()
```

## Testing

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

@pytest.fixture
async def db_session():
    """Create test database session."""
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost/test_db")
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        yield session
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.mark.asyncio
async def test_create_user(db_session):
    """Test user creation."""
    user = User(
        id="user123",
        email="test@example.com",
        full_name="Test User"
    )
    
    db_session.add(user)
    await db_session.commit()
    
    # Verify
    result = await db_session.execute(
        select(User).where(User.email == "test@example.com")
    )
    saved_user = result.scalar_one()
    assert saved_user.full_name == "Test User"
```

## Additional Resources

- SQLAlchemy 2.0 docs: https://docs.sqlalchemy.org/en/20/
- Alembic documentation: https://alembic.sqlalchemy.org/
- PostgreSQL optimization: https://www.postgresql.org/docs/current/performance-tips.html
