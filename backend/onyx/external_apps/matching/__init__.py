"""Maps an outbound sandbox request to a policy verdict.

Given a connected ``ExternalApp`` and a normalised request, ``match_action``
tests the app's code catalog of ``MatchRule``s (REST method+path, or GraphQL
operation+root-field) and returns the governing ``EndpointPolicy`` — or ``None``
when nothing recognises the request (off-catalog). Credential injection,
approval prompts and blocking are downstream business logic that act on this
verdict; this package only decides *which* verdict applies.

This ``__init__`` is the public facade; the proxy depends only on
``match_action`` and ``ProxiedRequest``. Internals (rule strategies, the GraphQL
parser, the match context) are free to change behind it.
"""

from onyx.external_apps.matching.engine import match_action
from onyx.external_apps.matching.request import ProxiedRequest

__all__ = ["match_action", "ProxiedRequest"]
