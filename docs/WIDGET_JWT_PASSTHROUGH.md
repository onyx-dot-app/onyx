# Chat Widget JWT Passthrough

The Onyx chat widget runs in the browser, so any credential you put in the page
is readable by the visitor. With an `api-key`, every visitor shares one service
account. With **JWT passthrough**, each visitor authenticates as themselves.

Use this guide when the page that hosts the widget already signs the visitor in
with the same identity provider (IdP) that Onyx uses.

## Scope: single-tenant deployments

JWT passthrough works on a single-tenant deployment, which means self-hosted
Onyx. It does not work on multi-tenant Onyx Cloud.

A multi-tenant deployment reads the workspace from the credential itself. See
`_get_tenant_id_from_request` in
`backend/ee/onyx/server/middleware/tenant_tracking.py`: it accepts an Onyx API
key or PAT prefix, a server-issued session token, or the anonymous-user cookie.
An external IdP token carries none of these, so the request falls back to the
default schema, which owns no workspace data. Use an API key on multi-tenant
Onyx until the backend binds a tenant to these tokens.

## What you get

| | `api-key` | JWT passthrough |
|---|---|---|
| Credential in the page | Long-lived shared secret | The visitor's own short-lived token |
| Onyx identity | One service account for all visitors | One Onyx user per visitor |
| Document permissions | Whatever the service account can read | Per visitor |
| Usage attribution | All traffic on one account | Per visitor |

The token still reaches the browser, but it is the visitor's own token. It
expires, it is scoped to that person, and a stolen copy grants no more than the
portal session it came from.

## How Onyx verifies the token

Onyx checks the `Authorization: Bearer <jwt>` header on every request that has
no session cookie. See `_check_for_saml_and_jwt` in `backend/onyx/auth/users.py`
and `verify_jwt_token` in `backend/onyx/auth/jwt.py`.

The sequence is:

1. Onyx downloads the verification key from the URL you configure. The endpoint
   can serve a JWKS document or a PEM public key. Onyx caches the result and
   refetches once if verification fails, so key rotation needs no restart.
2. Onyx verifies the RS256 signature and the `exp` claim. It also enforces
   `aud` and `iss` when you configure them.
3. Onyx reads the identity from the first valid email in the `email`,
   `preferred_username`, or `upn` claim.
4. Onyx applies the invite allowlist and the email-domain policy, the same
   rules every other login path uses.
5. Onyx finds the matching user, or creates one.

Onyx accepts **RS256 only**. Tokens signed with HS256 or ES256 are rejected.

## Configure Onyx

### 1. Point Onyx at the IdP verification key

Set the JWKS URL with an environment variable:

```bash
JWT_PUBLIC_KEY_URL=https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys
```

You can instead write `jwt_public_key_url` through the security settings API.
The environment variable wins when both are present.

The two paths differ in trust. An environment variable is operator
config-as-code, and Onyx fetches it as given. A value set through the API is
admin-supplied, so Onyx validates it against the outbound SSRF policy first and
requires HTTPS across every redirect hop.

### 2. Restrict which tokens Onyx accepts

```bash
JWT_EXPECTED_AUDIENCE=<the client id you registered for Onyx>
JWT_EXPECTED_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
```

**Set the audience.** Both settings are optional, and audience enforcement is
off while `JWT_EXPECTED_AUDIENCE` is unset. Without it, Onyx accepts any token
that IdP signed for any application. Because the portal and Onyx share an IdP,
that includes tokens minted for unrelated services.

### 3. Control who gets an Onyx account

Onyx creates a user on first request if the email is new. Limit this with the
invite list, or with the email-domain policy:

```bash
VALID_EMAIL_DOMAINS=yourcompany.com
```

Watch your seat count after you turn the widget on. Every portal user who opens
the widget becomes an Onyx user.

### 4. Allow the portal origin through CORS

The browser calls Onyx from the portal's origin, not from the Onyx origin:

```bash
CORS_ALLOWED_ORIGIN=https://portal.yourcompany.com
```

## Configure the widget

A function cannot ride an HTML attribute, so the host page assigns
`tokenProvider` as a JavaScript property. Drop the `api-key` attribute.

```html
<script type="module" src="https://cdn.onyx.app/widget/1.0/dist/onyx-widget.js"></script>

<onyx-chat-widget
  id="onyx-widget"
  backend-url="https://onyx.yourcompany.com/api"
  agent-id="42"
  mode="launcher"
></onyx-chat-widget>

<script type="module">
  const widget = document.getElementById("onyx-widget");
  widget.tokenProvider = () => fetchAccessTokenForOnyx();
</script>
```

Onyx calls `tokenProvider` before every request. Return a string, or a promise
that resolves to one. Assign it any time — the widget reads the property when it
sends a request, not when it mounts.

### Return a fresh token

Your function owns expiry. Return a token that is valid now:

```js
widget.tokenProvider = async () => {
  const token = await msalInstance.acquireTokenSilent({
    scopes: ["api://onyx/.default"],
  });
  return token.accessToken;
};
```

Most IdP SDKs cache the token and refresh it only when it is near expiry, so
calling the SDK per request is cheap. The widget also calls the provider again
for each retry attempt, so a token that expires during a backoff is replaced
rather than resent. The widget does not retry a 401, so a provider that returns
an already-expired token surfaces as an error in the chat panel.

### Conversations are scoped to the signed-in user

The widget keeps the transcript in `sessionStorage`. It tags each stored
transcript with the token subject (the `sub` claim), and it discards a stored
transcript whose subject does not match the current one. A second person who
signs in on the same tab therefore starts a fresh conversation and never sees
the first person's messages.

You can still clear the conversation on demand, for example on sign-out:

```js
widget.resetConversation();
```

## Verify the setup

1. Open the portal as a signed-in user and send a message in the widget.
2. Confirm the answer only cites documents that user may read.
3. Check the Onyx user list. The visitor's email should appear.
4. Send a request with an expired token. Onyx must reject it.
5. Send a token minted for a different audience. Onyx must reject it once
   `JWT_EXPECTED_AUDIENCE` is set.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Every request is unauthorized | `JWT_PUBLIC_KEY_URL` is unset, so Onyx never looks at the header. |
| `no email claim found` in the logs | The token carries none of `email`, `preferred_username`, `upn`. Add the claim at the IdP. |
| The browser blocks the request | The portal origin is missing from `CORS_ALLOWED_ORIGIN`. |
| `Invalid JWT token` in the logs | The signature, the algorithm, or `exp` failed. Confirm the IdP signs with RS256. |
| The widget reports a missing credential | Neither `api-key` nor `tokenProvider` is set on the element. |
