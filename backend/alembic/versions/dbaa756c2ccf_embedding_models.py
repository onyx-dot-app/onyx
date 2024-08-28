"""Embedding Models

Revision ID: dbaa756c2ccf
Revises: 7f726bad5367
Create Date: 2024-01-25 17:12:31.813160

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column, String, Integer, Boolean

from danswer.db.embedding_model import (
    get_new_default_embedding_model,
    get_old_default_embedding_model,
    user_has_overridden_embedding_model,
)
from danswer.db.models import IndexModelStatus

# revision identifiers, used by Alembic.
revision = "dbaa756c2ccf"
down_revision = "7f726bad5367"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "embedding_model",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_dim", sa.Integer(), nullable=False),
        sa.Column("normalize", sa.Boolean(), nullable=False),
        sa.Column("query_prefix", sa.String(), nullable=False),
        sa.Column("passage_prefix", sa.String(), nullable=False),
        sa.Column("index_name", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(IndexModelStatus, native=False),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # since all index attempts must be associated with an embedding model,
    # need to put something in here to avoid nulls. On server startup,
    # this value will be overriden
    EmbeddingModel = table(
        "embedding_model",
        column("id", Integer),
        column("model_name", String),
        column("model_dim", Integer),
        column("normalize", Boolean),
        column("query_prefix", String),
        column("passage_prefix", String),
        column("index_name", String),
        column(
            "status", sa.Enum(IndexModelStatus, name="indexmodelstatus", native=False)
        ),
    )
    # insert an embedding model row that corresponds to the embedding model
    # the user selected via env variables before this change. This is needed since
    # all index_attempts must be associated with an embedding model, so without this
    # we will run into violations of non-null contraints
    old_embedding_model = get_old_default_embedding_model()
    op.bulk_insert(
        EmbeddingModel,
        [
            {
                "model_name": old_embedding_model.model_name,
                "model_dim": old_embedding_model.model_dim,
                "normalize": old_embedding_model.normalize,
                "query_prefix": old_embedding_model.query_prefix,
                "passage_prefix": old_embedding_model.passage_prefix,
                "index_name": old_embedding_model.index_name,
                "status": old_embedding_model.status,
            }
        ],
    )
    # if the user has not overridden the default embedding model via env variables,
    # insert the new default model into the database to auto-upgrade them
    if not user_has_overridden_embedding_model():
        new_embedding_model = get_new_default_embedding_model(is_present=False)
        op.bulk_insert(
            EmbeddingModel,
            [
                {
                    "model_name": new_embedding_model.model_name,
                    "model_dim": new_embedding_model.model_dim,
                    "normalize": new_embedding_model.normalize,
                    "query_prefix": new_embedding_model.query_prefix,
                    "passage_prefix": new_embedding_model.passage_prefix,
                    "index_name": new_embedding_model.index_name,
                    "status": IndexModelStatus.FUTURE,
                }
            ],
        )

    op.add_column(
        "index_attempt",
        sa.Column("embedding_model_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE index_attempt SET embedding_model_id=1 WHERE embedding_model_id IS NULL"
    )
    op.alter_column(
        "index_attempt",
        "embedding_model_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "index_attempt__embedding_model_fk",
        "index_attempt",
        "embedding_model",
        ["embedding_model_id"],
        ["id"],
    )
    op.create_index(
        "ix_embedding_model_present_unique",
        "embedding_model",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'PRESENT'"),
    )
    op.create_index(
        "ix_embedding_model_future_unique",
        "embedding_model",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'FUTURE'"),
    )


def downgrade() -> None:
    op.drop_constraint(
        "index_attempt__embedding_model_fk", "index_attempt", type_="foreignkey"
    )
    op.drop_column("index_attempt", "embedding_model_id")
    op.drop_table("embedding_model")
    op.execute("DROP TYPE IF EXISTS indexmodelstatus;")
