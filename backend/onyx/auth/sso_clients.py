"""Hardened OIDC client for multi-IdP SSO. Two guarantees on top of the
stock client: the email claim is trusted only when the IdP marks it
verified, and the discovery document's issuer must own the configured
discovery URL, so one provider's tokens cannot be replayed against another
provider's callback (OIDC mix-up defense)."""

from urllib.parse import unquote
from urllib.parse import urlsplit

from httpx_oauth.clients.openid import BASE_SCOPES
from httpx_oauth.clients.openid import OpenID
from httpx_oauth.exceptions import GetIdEmailError


class OpenIDConfigurationIssuerMismatch(ValueError):
    """The discovery document's issuer does not own the configured URL."""


def _fully_decoded(path: str) -> tuple[str, bool]:
    """Percent-decode until the string stops changing, so N-times-encoded input
    collapses to its real form before validation. Returns (decoded, converged).
    The loop is bounded to avoid a pathological input; a path that has not
    stabilized within the bound is treated as hostile and the caller fails
    closed rather than validating a still-encoded string."""
    for _ in range(8):
        once = unquote(path)
        if once == path:
            return path, True
        path = once
    return path, False


def validate_issuer_owns_config_url(
    issuer: str | None, openid_configuration_endpoint: str
) -> None:
    """Per OIDC Discovery, the configuration document lives directly under the
    issuer's own URL. Compare scheme and host exactly and require a path
    boundary, so a look-alike host (issuer.attacker.com) cannot pass. Relative
    path segments are rejected outright, otherwise `issuer/../evil` would clear
    the prefix test yet resolve outside the issuer path on the same host. The
    path is decoded to a fixed point first, so single- or multiply-encoded
    traversal (%2e, %252e, ...) is caught regardless of how many times a server
    might decode it. A document that fails this is misconfigured or an
    impersonation attempt."""
    if not issuer:
        raise OpenIDConfigurationIssuerMismatch("discovery document has no issuer")

    iss = urlsplit(issuer)
    cfg = urlsplit(openid_configuration_endpoint)
    decoded_path, converged = _fully_decoded(cfg.path)
    has_relative_segment = not converged or any(
        segment in (".", "..") for segment in decoded_path.split("/")
    )
    issuer_path = iss.path.rstrip("/")
    same_origin = (iss.scheme.lower(), iss.netloc.lower()) == (
        cfg.scheme.lower(),
        cfg.netloc.lower(),
    )
    path_owned = cfg.path == issuer_path or cfg.path.startswith(issuer_path + "/")
    if (
        not iss.scheme
        or not iss.netloc
        or not same_origin
        or has_relative_segment
        or not path_owned
    ):
        raise OpenIDConfigurationIssuerMismatch(
            f"OpenID discovery document issuer {issuer!r} does not own "
            f"the configured endpoint {openid_configuration_endpoint!r}"
        )


class VerifiedEmailOpenID(OpenID):
    """OpenID client that refuses to hand back an email the IdP has not
    verified. An absent email_verified claim counts as unverified, since a
    mutable, unverified email claim is exactly the nOAuth account-takeover
    vector. A response with no email at all is passed through unchanged and
    rejected by the login flow's existing no-email handling."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        openid_configuration_endpoint: str,
        name: str = "openid",
        base_scopes: list[str] | None = BASE_SCOPES,
    ):
        super().__init__(
            client_id,
            client_secret,
            openid_configuration_endpoint,
            name=name,
            base_scopes=base_scopes,
        )
        validate_issuer_owns_config_url(
            self.openid_configuration.get("issuer"), openid_configuration_endpoint
        )

    @property
    def expected_issuer(self) -> str:
        """The issuer this client is pinned to, for callers that validate
        tokens or store per-provider metadata."""
        return str(self.openid_configuration["issuer"])

    async def get_id_email(self, token: str) -> tuple[str, str | None]:
        async with self.get_httpx_client() as client:
            response = await client.get(
                self.openid_configuration["userinfo_endpoint"],
                headers={**self.request_headers, "Authorization": f"Bearer {token}"},
            )

            if response.status_code >= 400:
                raise GetIdEmailError(response=response)

            # A malformed userinfo body must surface as a controlled login
            # rejection, not a raw JSON/attribute error out of the callback.
            try:
                data = response.json()
            except ValueError as e:
                raise GetIdEmailError(
                    "Userinfo response was not valid JSON", response=response
                ) from e
            if not isinstance(data, dict):
                raise GetIdEmailError(
                    "Userinfo response was not a JSON object", response=response
                )

            sub = data.get("sub")
            if not isinstance(sub, str) or not sub:
                raise GetIdEmailError(
                    "Userinfo response missing a string 'sub'", response=response
                )

            email = data.get("email")
            if email is not None and not isinstance(email, str):
                raise GetIdEmailError(
                    "Userinfo 'email' was not a string", response=response
                )
            if email is not None and data.get("email_verified") is not True:
                raise GetIdEmailError(
                    "Identity provider did not mark the email as verified",
                    response=response,
                )

            return sub, email
