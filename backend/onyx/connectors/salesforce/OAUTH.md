# Salesforce OAuth setup

Onyx uses the OAuth 2.0 authorization code flow with S256 PKCE. Use a
Salesforce External Client App (ECA). Salesforce recommends ECAs for new
integrations.

## Choose the deployment model

Onyx Cloud uses an Onyx-managed packaged ECA. All cloud tenants use one
canonical callback and client configuration. A Salesforce administrator
installs the package and applies local access policies.

A self-hosted Onyx deployment uses a customer-owned local ECA. Its callback
must match that deployment's `WEB_DOMAIN`. Do not reuse the client configuration
for a different domain.

## Prerequisites

- Use a stable HTTPS `WEB_DOMAIN`.
- Enable My Domain in the Salesforce organization.
- Use a Salesforce administrator account to create and configure the ECA.
- Decide which users or permission sets can authorize Onyx.
- Store the ECA consumer secret in a secret manager.

## Create a local ECA for self-hosted Onyx

1. In Salesforce Setup, open **External Client App Manager**.
2. Select **New External Client App**.
3. Set **Distribution State** to **Local**.
4. Enable OAuth.
5. Set the callback URL to:

   ```text
   {WEB_DOMAIN}/connector/oauth/callback/salesforce
   ```

6. Add these OAuth scopes:
   - **Manage user data via APIs** (`api`)
   - **Perform requests at any time** (`refresh_token`)
7. Require a secret for the web server flow.
8. Require a secret for the refresh token flow.
9. Require PKCE for supported authorization flows. Onyx uses S256.
10. Enable refresh token rotation.
11. Save the ECA. Copy its consumer key and consumer secret.

The client secret is required. OAuth stays disabled when either client value is
absent.

Salesforce can take several minutes to activate a new app or policy change.

## Set permitted users

Use the ECA **Policies** tab to select a permitted-user policy.

For controlled deployments, select **Admin approved users are pre-authorized**.
Assign the ECA to the required profiles or permission sets. Each authorizing
user also needs access to the Salesforce objects that Onyx will index.

Use **All users may self-authorize** only when organization policy permits it.
Salesforce still applies each user's object and field permissions.

## Configure Onyx

Set both variables on the API server and all background workers:

```text
SALESFORCE_CLIENT_ID=<ECA consumer key>
SALESFORCE_CLIENT_SECRET=<ECA consumer secret>
```

Restart the affected Onyx services after a configuration change.

In the Onyx Salesforce connector form, select OAuth and enter the Salesforce
My Domain URL. Use only the organization root, for example:

```text
https://company.my.salesforce.com
```

For a sandbox, use its My Domain host, for example:

```text
https://company--dev.sandbox.my.salesforce.com
```

Do not enter `login.salesforce.com`, a path, a query, or a custom port.

## Onyx Cloud

Onyx Cloud supplies the packaged ECA client configuration. Do not create a
separate local ECA for the cloud callback.

Install the Onyx package in the Salesforce organization. Then configure the
subscriber policies and permitted users. Enter the organization's My Domain URL
in Onyx before authorization.

## Token behavior

Salesforce returns an access token and a refresh token after authorization.
Onyx encrypts both tokens in PostgreSQL.

Onyx refreshes credentials after Salesforce reports an invalid session. If
Salesforce rotates the refresh token, Onyx stores the new token. If Salesforce
returns no new refresh token, Onyx keeps the current token.

Revoking the app, changing its scopes, changing its permitted-user policy, or
expiring a refresh token can require authorization again.

## Manual credential fallback

OAuth is optional. The connector still accepts:

- Salesforce username
- Salesforce password
- Salesforce security token
- Sandbox selection

Use this fallback when an ECA cannot be installed. Salesforce login policy can
block username and password authentication. OAuth is the recommended method.

## Troubleshooting

### OAuth is not configured

Confirm that both Salesforce client variables exist in the API server and
background worker environments. Restart both services.

### Callback URL mismatch

Compare the ECA callback with the canonical callback exactly. Check the scheme,
host, base path, and port in `WEB_DOMAIN`.

### My Domain is rejected

Enter an HTTPS My Domain root. Remove paths, queries, fragments, credentials,
and non-default ports.

### User cannot authorize

Check the ECA permitted-user policy. For pre-authorized access, assign the
correct profile or permission set.

### Salesforce returns `invalid_grant`

The authorization code can be used once and expires quickly. Start a new
authorization. Also check the callback, PKCE policy, client secret, and refresh
token policy.

### No refresh token is returned

Confirm that the ECA has the `refresh_token` scope. Check the user's prior
grants and the ECA refresh token policy. Revoke the old grant, then authorize
again if required.

### OAuth state is invalid

OAuth state is one-use and expires after ten minutes. Start authorization again
in the same Onyx tenant.

## Salesforce references

- [External Client Apps and Connected Apps](https://developer.salesforce.com/docs/platform/mobile-sdk/guide/connected-apps.html)
- [Create an External Client App](https://developer.salesforce.com/docs/platform/mobile-sdk/guide/eca-create.html)
- [External Client App metadata](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_externalclientapplication.htm)
- [Second-generation managed package workflow](https://developer.salesforce.com/docs/atlas.en-us.pkg2_dev.meta/pkg2_dev/sfdx_dev_dev2gp_workflow.htm)
- [Partner OAuth security requirements](https://developer.salesforce.com/docs/platform/isvforce/guide/secure-code-ac-eca.html)
