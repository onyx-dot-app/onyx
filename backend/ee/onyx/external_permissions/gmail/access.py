from onyx.access.models import ExternalAccess


def get_group_mail_access(group_email: str) -> ExternalAccess:
    """Mail a Collaborative Inbox group delivered goes to the group's id and to
    no mailbox owner."""
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={group_email},
        is_public=False,
    )
