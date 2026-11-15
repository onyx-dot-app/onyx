# Microsoft Graph connectors

> The shared Microsoft layer gives every Microsoft connector app-only Entra
> auth, national-cloud hosts, Graph error mapping, drive delta paging and
> SharePoint REST permission reads. This document also covers the SharePoint and
> OneDrive connectors; Outlook and Teams have their own documents.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE syncs SharePoint and OneDrive permissions and Entra groups
(`ee/onyx/external_permissions/sharepoint/`, `ee/onyx/external_permissions/onedrive/`,
`ee/onyx/external_permissions/microsoft_utils/`).

---

## User experience

An admin registers an Entra app, grants it Graph permissions, and connects it
with a client secret or a certificate. For a national cloud such as GCC High,
they set the authority and Graph hosts. For SharePoint they pick site URLs, or
none for every site, and can exclude sites and paths. For OneDrive they pick
users' drives. Search returns one document per file and per site page. With EE
permission sync, only the people SharePoint lets read a file can find it.

A client-secret app cannot read SharePoint permissions, so permission sync and
Teams channel files need a certificate. The checks card says which grant is
missing. A Graph host and authority host that do not form one known cloud fail
when the connector is built.

---

## Scope

This document holds the rules of the shared Microsoft layer and of the
SharePoint and OneDrive connectors. Its neighbours own:
- [[connectors]]: the interfaces, binding, gateway and prune contracts.
- [[connector-capability-checks]]: the check runner. SharePoint, OneDrive and
  Outlook register named checks that share the Microsoft sign-in probe.
- [[permission-sync]]: the EE doc sync and Entra group sync, which use the
  SharePoint REST reads and the gateways.
- [[outlook]] and [[teams]]: their own connector rules on top of this layer.

---

## Architecture

**Auth.** `connectors/microsoft_utils/graph_auth.py:build_msal_app` takes
explicit client id, tenant and secret or certificate values. Each connector
maps its own credential keys onto it. `MicrosoftAuthMethod.supports_sharepoint_rest`
is true only for a certificate.

**National clouds.** `connectors/microsoft_utils/config.py:MicrosoftCloudBinding`
adds `authority_host` and `graph_api_host` to each Microsoft config as IDENTITY
fields, because a Graph object id resolves only in its own cloud.
`connectors/microsoft_utils/graph_env.py:resolve_microsoft_environment` maps
the two hosts to an office365 `AzureEnvironment` and the SharePoint domain
suffix, and raises `ConnectorValidationError` for an unknown pair. The
connectors call it when they are built.

**Errors.** `connectors/microsoft_utils/graph_errors.py` maps Graph and MSAL
failures to the validation exception family. `MicrosoftGraphError` is a
`SourceApiError`, so a failed check shows the request and response. Its
`is_permanent_refusal` tells a refusal that a retry cannot fix from an outage.

**Shared checks.** The SharePoint, OneDrive and Outlook checks share their
sign-in probe and its row text
(`connectors/capability_checks/microsoft_check_text.py`). Their later probes
depend on it.

**SharePoint permission reads.** `connectors/microsoft_utils/sharepoint_rest.py`
reads role assignments over SharePoint REST and returns plain models, so the EE
permission code never holds an office365 object. SharePoint and Teams both use
it.

**SharePoint gateway.** `SharepointSourceOperations` declares `msal`,
`requests` and `office365` in `sdk_modules`, so it is the only importer of
those modules in the SharePoint connector and its EE permission code. It keeps
one office365 REST context per thread.

---

## Contracts and traps

1. `domain-suffix-ignored` **`sharepoint_domain_suffix` is ignored.** The
   connector uses the suffix of the cloud that `graph_api_host` selects and
   logs a warning when the stored value differs. The field stays for stored
   configs and is COSMETIC.
2. `sharing-link-public-is-behavior` **`treat_sharing_link_as_public` is a
   BEHAVIOR field.** It changes the access list of indexed documents, so an
   edit re-indexes everything.
3. `ad-enumeration-ee-only` **`exhaustive_ad_enumeration` is read only by the
   EE group sync, the EE perm-sync probe and the checks.** Indexing ignores it, so a change needs no
   re-index.
4. `validation-error-not-runtime-error` **Raising `ConnectorValidationError`
   from auth code is not the same as `RuntimeError`.** A validation error
   cancels the index attempt and counts toward marking the credential invalid
   (`connectors/microsoft_utils/graph_auth.py` module docstring).
5. `checkpoint-aliases` **A checkpoint shape change needs aliases.**
   `SharepointConnectorCheckpoint` reads older field names through
   `AliasChoices` (`connectors/sharepoint/connector.py:SharepointConnectorCheckpoint`). In-flight attempts keep their saved checkpoints across a
   deploy, so keep that pattern, or they fail to resume
   ([[connectors#checkpoint-compatible]]).
6. `site-urls-full` **Site URLs must be full.** The SharePoint `sites` field
   accepts only `https` URLs with a `/sites/`, `/teams/` or `/personal/` path
   (`connectors/sharepoint/config.py:is_site_url_well_formed`).

---

## Dependencies

- [[connectors]]: interfaces, binding, gateway and prune contracts.
- [[connector-capability-checks]]: runs the SharePoint and OneDrive named checks.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/microsoft_utils/`,
  `backend/tests/unit/onyx/connectors/sharepoint/` and
  `backend/tests/unit/onyx/connectors/onedrive/`.
- Daily tests against a live tenant: `backend/tests/daily/connectors/sharepoint/`
  and `backend/tests/daily/connectors/onedrive/`.
