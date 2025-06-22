# """drive-canonical-ids

# Revision ID: 12635f6655b7
# Revises: 03bf8be6b53a
# Create Date: 2025-06-20 14:44:54.241159

# """

# from alembic import op
# import sqlalchemy as sa
# from onyx.document_index.factory import get_default_document_index
# from onyx.db.search_settings import get_active_search_settings
# from onyx.db.search_settings import SearchSettings


# # revision identifiers, used by Alembic.
# revision = "12635f6655b7"
# down_revision = "03bf8be6b53a"
# branch_labels = None
# depends_on = None


# def active_search_settings() -> tuple[SearchSettings, SearchSettings]:
#     result = op.get_bind().execute(
#         sa.text(
#             """
#         SELECT * FROM search_settings WHERE status = 'PRESENT' ORDER BY id DESC LIMIT 1
#         """
#         )
#     )
#     search_settings = result.scalars().fetchall()
#     result2 = op.get_bind().execute(
#         sa.text(
#             """
#         SELECT * FROM search_settings WHERE status = 'FUTURE' ORDER BY id DESC LIMIT 1
#         """
#         )
#     )
#     search_settings_future = result2.scalars().fetchall()
#     return search_settings, search_settings_future


# def upgrade() -> None:
#     active_search_settings = get_active_search_settings(db_session)
#     document_index = get_default_document_index(
#         active_search_settings.primary,
#         active_search_settings.secondary,
#     )


# def downgrade() -> None:
#     # this is a one way migration, so no downgrade.
#     # It wouldn't make sense to store the extra query parameters
#     # and duplicate documents to allow a reversal.
#     pass
