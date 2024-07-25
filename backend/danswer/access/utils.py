def prefix_user(user_id: str) -> str:
    """Prefixes a user ID to eliminate collision with group names.
    This assumes that groups are prefixed with a different prefix."""
    return f"user_id:{user_id}"


def prefix_user_group(user_group_name: str) -> str:
    """Prefixes a user group name to eliminate collision with user IDs.
    This assumes that user ids are prefixed with a different prefix."""
    return f"group:{user_group_name}"
