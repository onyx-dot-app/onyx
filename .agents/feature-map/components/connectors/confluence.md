# Confluence

> The Confluence connector indexes pages and attachments from Confluence Cloud
> or Data Center, with page and attachment URLs as document ids. A mode sets
> its scope, and its client renews a rotating credential under the
> credential provider's lock.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE syncs page and space permissions and Confluence groups
(`ee/onyx/external_permissions/confluence/`).

---

## User experience

An admin connects a Confluence site with an API token, a scoped token or an
OAuth sign-in. They then pick what to index: everything, some spaces, some pages
(optionally with their child pages), or a CQL query. Attachments are on by
default. The connector page breaks the indexed documents down by space and by
the configured pages. A configured space or page shows there also when no
document is under it.

When the site URL does not match the site an OAuth account was authorized for,
the form refuses it. A CQL query with its own `lastModified` filter or
`ORDER BY` fails validation, because each sync adds its own.

---

## Scope

This document holds the Confluence rules: the indexing modes, URL document
ids, the site binding, the per-call credential lock and the hierarchy
breakdown. Its neighbours own:
- [[connectors]]: the interfaces, typed config, binding and prune contracts.
- [[connector-capability-checks]]: the check runner. Confluence registers named
  checks, and its CQL check reports on the `cql_query` field.
- [[permission-sync]]: the EE doc and group sync, which call the Confluence
  gateway.

---

## Architecture

**Indexing mode.** `connectors/confluence/config.py:get_indexing_mode` picks one
mode from the config. The first set one wins: CQL query, then page ids, then
spaces, then everything. The form sends every tab's fields, so a config can
hold values for several modes. In page mode, the spaces count too: the scope is
their union. The CQL shape rules live in `connectors/atlassian_query.py`,
which Jira shares, so a change there reaches Jira too.

**Checkpoint.** `ConfluenceCheckpoint` holds only `next_page_url`. The connector
implements no `LoadConnector` or `PollConnector`. Its slim listing honors the
indexing start, so a prune also removes pages last changed before it
([[connectors#honor-time-window]]).

**Credentials.** Confluence is a `CredentialsConnector`. `load_credentials`
raises `NotImplementedError`. Each API call runs inside
`with self._credentials_provider`, renews the credential when it rotated, and
rebuilds the client
(`connectors/confluence/source_operations.py:_OnyxConfluence._call_with_retries`).

**Hierarchy breakdown.** `ConfluenceConnectorConfig.hierarchy_breakdown_sections`
lists every space plus the configured spaces and pages. Only fields of the mode
in use name nodes. A page node's raw id is the page URL, so
`hierarchy_node_key` maps it to the numeric page id the config uses. Space keys
match without case. A leaf page has no hierarchy node, only a document, so the
section allows a document to stand for a node (`nodes_can_be_documents`).

---

## Contracts and traps

1. `url-ids-reparsed` **Document ids are URLs, and re-index parses them.**
   `connectors/confluence/connector.py:ConfluenceConnector.reindex` extracts the
   page id with
   `connectors/confluence/config.py:extract_page_id_from_url`, which accepts
   `/pages/<id>/` and `pageId=<id>`. A failure that carries a bare page id can
   never be repaired. Pass the page URL as the failure id
   ([[connectors#failure-id-is-document-id]]).
2. `site-fields-are-identity` **`wiki_base` and `is_cloud` are IDENTITY
   fields.** They are part of every document id. A change re-indexes and prunes
   everything.
3. `loose-site-comparison` **Site URL comparison is looser than for other
   sources.** `connectors/confluence/config.py:ConfluenceCredentialBinding.comparison_values` drops a trailing
   slash, and on Cloud a trailing `/wiki`, because the connector strips the
   slash and adds `/wiki` to Cloud document ids. The OAuth site check
   (`connectors/confluence/config.py:ConfluenceCredentialBinding.validate_credential`) compares scheme and host,
   so an `http` URL does not match an `https` grant. The check passes when the
   credential records no `wiki_base`, so a token refresh must keep the site
   keys (`connectors/confluence/source_operations.py:_OAUTH_SITE_KEYS`): the
   refresh response does not return them.
4. `one-call-per-credential` **Parallel calls on one credential run one at a
   time.** Each call runs inside `with self._credentials_provider`. With the
   DB-backed provider, that holds the lock for that credential. Capability checks on one gateway,
   and pairs that share a credential, wait on each other.
5. `probe-builds-new-client` **`probe_site` builds a new client**
   (`connectors/confluence/source_operations.py:ConfluenceSourceOperations.probe_site`). The probe
   swaps the client's connection settings, and other threads may be using the
   cached client.
6. `mode-change-unknown-direction` **A mode change has no scope direction.**
   `connectors/confluence/config.py:confluence_planning_rule` reports UNKNOWN for a change between two modes
   other than everything, and for any change of the CQL query. The edit plan
   then has no recommendation and asks the admin to pick how to reconcile.

---

## Dependencies

- [[connectors]]: interfaces, typed config, binding and prune contracts.
- [[connector-capability-checks]]: runs the Confluence named checks.
- [[cc-pairs-and-creds]]: the Confluence Cloud OAuth flow stores
  `wiki_base` on the credential.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/confluence/`.
- External dependency tests:
  `backend/tests/external_dependency_unit/connectors/confluence/`.
- Daily tests against a live site: `backend/tests/daily/connectors/confluence/`.
