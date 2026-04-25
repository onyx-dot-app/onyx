# knowledge_layer/db/models.py
from __future__ import annotations

import datetime
import enum

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Standalone declarative base for the knowledge layer.

    At migration time, alembic/env.py imports this Base alongside
    onyx.db.models.Base so both sets of tables are managed together.
    """
    pass


class IngestStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TopicExt(Base):
    __tablename__ = "kl_topic_ext"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    watch_path: Mapped[str] = mapped_column(sa.String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    wiki_pages: Mapped[list[WikiPage]] = relationship(
        "WikiPage", back_populates="topic", cascade="all, delete-orphan"
    )
    ingest_runs: Mapped[list[IngestRun]] = relationship(
        "IngestRun", back_populates="topic", cascade="all, delete-orphan"
    )


class WikiPage(Base):
    __tablename__ = "kl_wiki_page"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        sa.Integer, sa.ForeignKey("kl_topic_ext.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    vespa_doc_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    topic: Mapped[TopicExt] = relationship("TopicExt", back_populates="wiki_pages")
    versions: Mapped[list[WikiPageVersion]] = relationship(
        "WikiPageVersion", back_populates="page", cascade="all, delete-orphan",
        order_by="WikiPageVersion.version_num"
    )
    outgoing_refs: Mapped[list[CrossRef]] = relationship(
        "CrossRef", foreign_keys="CrossRef.from_page_id", back_populates="from_page",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint("topic_id", "slug", name="uq_kl_wiki_page_topic_slug"),
    )


class WikiPageVersion(Base):
    __tablename__ = "kl_wiki_page_version"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        sa.Integer, sa.ForeignKey("kl_wiki_page.id", ondelete="CASCADE"), nullable=False
    )
    version_num: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    page: Mapped[WikiPage] = relationship("WikiPage", back_populates="versions")

    __table_args__ = (
        sa.UniqueConstraint("page_id", "version_num", name="uq_kl_wiki_page_version"),
    )


class CrossRef(Base):
    __tablename__ = "kl_cross_ref"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    from_page_id: Mapped[int] = mapped_column(
        sa.Integer, sa.ForeignKey("kl_wiki_page.id", ondelete="CASCADE"), nullable=False
    )
    to_slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    link_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    from_page: Mapped[WikiPage] = relationship(
        "WikiPage", foreign_keys=[from_page_id], back_populates="outgoing_refs"
    )


class IngestRun(Base):
    __tablename__ = "kl_ingest_run"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        sa.Integer, sa.ForeignKey("kl_topic_ext.id", ondelete="CASCADE"), nullable=False
    )
    source_doc_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    source_content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[IngestStatus] = mapped_column(
        sa.Enum(IngestStatus, native_enum=False), nullable=False, default=IngestStatus.PENDING
    )
    error_msg: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    topic: Mapped[TopicExt] = relationship("TopicExt", back_populates="ingest_runs")
