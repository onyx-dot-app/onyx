from onyx.access.models import ExternalAccess


def get_group_mail_access(group_email: str) -> ExternalAccess:
    """Access for mail a Collaborative Inbox group delivered: the readers the
    Gmail group sync resolves for that group, and no mailbox owner."""
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={group_email},
        is_public=False,
    )
