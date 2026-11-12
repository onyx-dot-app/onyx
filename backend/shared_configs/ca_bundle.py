import os
import sys

# Homebrew's ca-certificates merges the keychain's trusted certs into this
# bundle, so a proxy CA that certifi's public roots lack is found here.
_HOMEBREW_CA_BUNDLES = (
    "/opt/homebrew/etc/ca-certificates/cert.pem",
    "/usr/local/etc/ca-certificates/cert.pem",
)


def prefer_homebrew_ca_bundle_on_macos() -> None:
    """Route httpx, OpenSSL and requests through the keychain-aware Homebrew bundle.

    Managed laptops sit behind a TLS-intercepting proxy whose CA only the keychain
    trusts. Must run before any client is built. Nothing deployable runs on macOS,
    so Linux images are untouched.
    """
    if sys.platform != "darwin" or os.environ.get("SSL_CERT_FILE"):
        return
    for bundle in _HOMEBREW_CA_BUNDLES:
        if not os.path.exists(bundle):
            continue
        os.environ["SSL_CERT_FILE"] = bundle
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
        return
