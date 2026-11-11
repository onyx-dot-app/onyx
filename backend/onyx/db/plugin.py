from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.enums import MarketplaceKind
from onyx.db.models import Marketplace, Plugin


def delete_user_upload_plugins__no_commit(db_session: Session, user_id: UUID) -> None:
    """Delete the plugins in the user's "My uploads" before a user delete.

    Until reads move to the plugin tables, the legacy skill rows are the source
    of truth and the user-delete guard checks only them. A plugin copied there
    can outlive its skill (delete, transfer, publish) and would block the
    marketplace cascade. The re-sync migrations rebuild any plugin that a live
    skill still needs.
    """
    db_session.execute(
        delete(Plugin).where(
            Plugin.marketplace_id.in_(
                select(Marketplace.id).where(
                    Marketplace.kind == MarketplaceKind.USER_UPLOADS,
                    Marketplace.owner_user_id == user_id,
                )
            )
        )
    )
