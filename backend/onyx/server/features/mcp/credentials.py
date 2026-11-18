"""Fingerprints of MCP OAuth client registrations."""

from mcp.shared.auth import OAuthClientInformationFull

from onyx.oauth.authorization_attempt import canonical_json_fingerprint


def mcp_oauth_client_information_fingerprint(
    client_information: OAuthClientInformationFull,
) -> str:
    return canonical_json_fingerprint(
        client_information.model_dump(
            mode="json",
            exclude_none=True,
            by_alias=True,
        ),
    )
