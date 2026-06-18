"""Mobile SSO bridge.

Backend support for native-mobile (Expo / React Native) OAuth/SSO login. The
app runs the OAuth dance in the system browser (reusing the existing, already
registered IdP callback) and the backend returns a single-use, PKCE-bound
one-time code over a custom-scheme deep link — never a token. The app then swaps
that code for the existing revocable session token (as a Bearer) at
``/auth/mobile/sso/exchange``.

Provider-genericity is achieved by the single shared ``complete_mobile_sso``
helper that each provider callback calls (Google today; OIDC / SAML / Apple
later), not a new abstraction layer.
"""
