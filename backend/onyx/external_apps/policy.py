from onyx.db.enums import EndpointPolicy

# The effective policy for a recognised catalog action that the admin has not
# explicitly configured. An action's existence + display come from the code
# catalog; the absence of a stored row means "not yet decided" -> prompt.
DEFAULT_ACTION_POLICY = EndpointPolicy.ASK


def resolve_policy(
    action_id: str,
    stored: dict[str, EndpointPolicy],
) -> EndpointPolicy:
    """Resolve the effective policy for a *recognised* catalog action: the
    admin's stored override if present, else the default (``ASK``).

    This is the single seam shared by the admin policy view
    (``action_policy_views``) and live request matching (``match_action``), so
    the admin preview and the proxy can never disagree about a configured
    action. Off-catalog requests (nothing matched) are handled one level up in
    ``match_action`` and never reach here.
    """
    return stored.get(action_id, DEFAULT_ACTION_POLICY)
