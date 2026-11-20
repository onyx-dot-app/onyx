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

**Rate limiting.** Microsoft limits the resource units (RU) of each app
registration in a tenant: 1,250 to 6,250 RU per minute by license tier. With
`ENABLE_SOURCE_API_LIMITER` on, `connectors/source_api_limiter.py:build_source_api_limiter`
gives SharePoint, OneDrive, Outlook and Teams a `RedisSourceApiLimiter` keyed
`microsoft:<directory id>:<client id>` (`microsoft_app_key`), so every
connector on one app shares one budget and one pause, whatever credential row
holds the app. The budget is `MICROSOFT_GRAPH_RU_PER_MINUTE` (6,250) in a 10 s
window. A new window starts at `MICROSOFT_START_SHARE` (0.2) and learns the
limit from 429 answers, with the cut and growth rules of [[google-drive]].
`connectors/microsoft_utils/request_pacer.py:MicrosoftRequestPacer` takes the
cost of each call before it goes out: `graph_call_type` reads the type from
the URL and `RU_COSTS` gives its cost (item, delta page and `/content` 1,
children page 2, permission 5, SharePoint REST 5 as an estimate). A fetch of a
pre-authenticated download link (`MicrosoftCall.LINK_DOWNLOAD`), also the
redirect target of `/content`, is not a Graph call: it costs 0 RU and takes one
turn from a lane of its own, `DOWNLOAD_LIMITER_API` ("download"), with its own
learned rate (`MICROSOFT_DOWNLOAD_BUDGET`, a ceiling of 6,000 fetches per
minute from the same start share) and its own pause. `/content` does not follow
its redirect, so the fetch of the target takes its turn from that lane. The raw GET
(`graph_api_get_json`), the downloads in
`connectors/microsoft_utils/drive_items.py`, and every request
of an office365 SDK client from `prepare_sdk_client` pass through it. Each try
of a retry takes its cost again. On a 429 or 503 with `Retry-After`, the pacer
calls `report_retry_after` for the lane of the call: the limiter stores the end
time in
`<tenant>:source_api_limit:microsoft:<directory id>:<client id>:<api>:blocked_until`
(the later time wins), and every `acquire` of that lane by every worker on the
app waits for it. A throttle of the download host never pauses or cuts the
Graph lane. The wait checks the stop signal. A 429 also counts toward a cut of
the lane. The limiter logs "graph asked its callers to wait Ns (Retry-After);
every call of the shared pause ... waits Ns." with a hash of the key in place
of the key, and counts
`onyx_source_api_limiter_units_total` (RU taken),
`onyx_source_api_limiter_pauses_total` and
`onyx_source_api_limiter_paused_seconds_total`
(`server/metrics/source_api_metrics.py`). Every Graph and REST request carries
`User-Agent: ISV|Onyx|Onyx/<version>`, also with the limiter off: Microsoft
gives such traffic priority.

**RU per minute.** `connectors/microsoft_utils/config.py:MicrosoftRateBudget`
adds the optional `ru_per_minute` field to the four configs. It is COSMETIC, so
an edit needs no re-index, and it is on the connector because a credential
change runs the connector again. The connectors accept the argument and do not
read it: `build_source_api_limiter` reads it from the stored config. With a
value and a `cc_pair_id`, the connector gets a window of its own, keyed
`microsoft:cc_pair:<id>`, at the full value from the start
(`microsoft_connector_budgets`), and a budget for 24 hours of 960 times the
value, which Redis counts by the hour (`backend/onyx/redis/redis_rate_window.py:try_take_from_day`).
It still reads and sets the pause of the app, and a 429 still cuts its window.
With no value, the connector shares the learned budget of the app.
`GET /manage/admin/credential/{id}/microsoft-rate-budgets`
(`server/documents/credential.py:list_microsoft_rate_budgets`, global
`MANAGE_CONNECTORS` only) lists the connectors on the same app on any
credential row (`backend/onyx/db/credentials.py:fetch_microsoft_app_cc_pairs`) with their
values and the sum, and no credential field. The connector form shows them
under the field
(`web/src/views/admin/connectors/AddConnectorPage/form/MicrosoftRateBudgetNote.tsx`).

**SharePoint stub listing.** `SharepointConnector` is a
`CheckpointedSlimConnector` with `listing_payload_type =
SharepointListingPayload`, so with `ENABLE_CONVERSION_STAGE` on, docfetching
lists it as stubs and the conversion stage fetches the documents
([[indexing-pipeline]]). `retrieve_slim_docs_from_checkpoint` and
`load_from_checkpoint` run one walk (`_walk_from_checkpoint`) over sites,
drives, delta pages and site pages, with one checkpoint model. The listing
yields a `SlimDocumentStub` for each file that the fetching path keeps
(`connectors/sharepoint/listing.py:is_listable_drive_item`) and downloads
nothing. The payload holds the drive id, the item id, the list ids, the site
URL and the file fields. It also holds the listing's `downloadUrl`, encrypted
with `onyx.utils.encryption.encrypt_string_to_bytes` as credentials are
(plain text when the deployment has no key), and the time of the listing. A
site page is listed with no `canvasLayout`. The stub's time and size are
those of the document, so `drop_unchanged_stubs` drops an unchanged file. A
run starts the delta of a drive from a time token, as the fetching path does. The listing does not keep
the `@odata.deltaLink`: the walk drops items modified after the window end, so
a run that continued from that link would miss them.

**SharePoint full pass.** On a stub listing from the epoch, a drive with no
configured folder is not read with one delta stream. `_start_full_pass` takes
the delta cursor of the drive's state now (`token=latest`,
`SharepointSourceOperations.get_latest_delta_link`). The walk then reads the
folders with `/children`, `SHAREPOINT_LISTING_WORKERS` (8) pages at one time
(`_read_full_pass_folders`, `get_children_page`). The checkpoint holds the
pages still to read as a stack (`full_pass_folders`). `/children` can miss an
item that is written or moved during the walk, so the delta from the cursor
runs after the walk (`full_pass_catching_up`). The time window does not filter
its items: a moved item keeps its modified time. An incremental run reads one
delta stream for each drive. A children page costs 2 RU for each folder, so a
drive with many small folders costs more RU on a full pass than its delta.

**SharePoint conversion.** `SharepointConnector.resolve_targets` converts a
batch of stubs in a thread pool of `SHAREPOINT_CONVERSION_WORKERS` (16). A file
target makes one download from its listed link while the link is younger than
`connectors/sharepoint/listing.py:DOWNLOAD_URL_MAX_AGE` (45 minutes; links live about one hour),
which is no Graph call. An older link, a link that does not decrypt, and a
refused link (any other request error) fall back to `/drives/{d}/items/{i}/content`
(1 RU) in
`connectors/microsoft_utils/drive_items.py:extract_drive_item_content`. A
throttled link (429 or 503) does not fall back, because `/content` redirects to
the same download host: the pacer reports its Retry-After to the download lane
of the app, so every link download on the app pauses (Graph calls go on), and
the link is tried again while it is fresh. A link that stays throttled fails the
document. A link download costs 0 Graph RU. With
permission sync, it also makes the role-assignment reads from the list ids of
the payload. A
page target makes one read of the page with its canvas. No target makes a
metadata call, and the listing already yielded the hierarchy nodes. A target
with no payload goes through `reindex`. The first step of a listing sets
`listing_run_id` in the checkpoint, and each stub carries it. Conversion keeps
the group expansions of the permission reads in a
`SharedSharepointPermissionCache` for that run
(`connectors/microsoft_utils/sharepoint_access.py`): in the process and in
Redis under `sharepoint_group_expansion:<run id>:<hash>`, so the threads of
every worker share the expansion of a group in a run. The cache does not
lock a key: threads that miss the same group at the same time each read it,
and the last write wins. A later run, or a connector on
another credential, never reads these keys. The fetching path, the slim walk
and permission sync keep the expansions in the connector object only, for one
run, as before. The checkpoint no longer holds them. The docconversion
Postgres pool holds a connection for each file thread of the source with the
most threads (`docconversion_pool_size`).

**SharePoint inherited permissions.** A stub listing with permission sync
(and `treat_sharing_link_as_public` off) asks each delta page for
`Prefer: hierarchicalsharing` (`SharepointSourceOperations.get_delta_page`).
Graph then gives the `shared` facet only to an item with permissions of its
own. The listing sets `inherits_permissions` on a payload only when Graph
names the preference in `Preference-Applied` and the file has no `shared`
facet. Such a listing reads a full pass with the delta and not with
`/children`, which has no such signal. Conversion gives a file that inherits
the access of its parent folder, or of the library for a file at the root
(`SharepointConnector._inherited_access`): one read for each parent, kept in
Redis under `sharepoint_container_access:<hash>` for 10 minutes. Every other
file, and every page, gets a read of its own, as before.

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
6. `checkpoint-bounded` **The SharePoint checkpoint holds no document ids.**
   It is stored after each delta page, so a set that grows with the drive
   makes the stored bytes grow with the square of the drive.
   `seen_hierarchy_node_raw_ids` is cut when the walk leaves a drive and at
   `MAX_SEEN_HIERARCHY_NODE_IDS`. Graph can return one item on two delta pages;
   the item is then converted two times.
7. `download-url-encrypted-in-payload` **A listing payload holds `downloadUrl`
   only encrypted.** It is a credential for the file, so store it through
   `encrypt_string_to_bytes` and never log it. It expires in about an hour, so
   use it only while it is younger than `DOWNLOAD_URL_MAX_AGE`, and keep the
   `/content` fallback.
8. `site-urls-full` **Site URLs must be full.** The SharePoint `sites` field
   accepts only `https` URLs with a `/sites/`, `/teams/` or `/personal/` path
   (`connectors/sharepoint/config.py:is_site_url_well_formed`).

9. `inheritance-fails-closed` **A file inherits only when the listing is
   certain.** `inherits_permissions` is False when Graph did not answer
   `Preference-Applied`, when the file came from `/children`, when the parent
   cannot be read, and with `treat_sharing_link_as_public`. The file then gets
   a permission read of its own. Keep `shared` in the `$select` of every delta
   URL of such a listing, or every file looks as if it inherits.
10. `sdk-client-prepared` **Build an office365 client through
   `prepare_sdk_client`.** A `GraphClient` or `ClientContext` built without it
   sends requests that take no cost from the limiter and carry no User-Agent.
   The pacer is read for each request, because the factory gives a connector
   its limiter after its credentials.
11. `call-cost-from-url` **A new Graph call gets its cost from its URL.** Add a
   pattern to `graph_call_type` when a new endpoint has a cost above 1 RU.

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
