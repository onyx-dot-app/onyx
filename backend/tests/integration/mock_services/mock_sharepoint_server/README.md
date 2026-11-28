# Mock Microsoft Graph and SharePoint server

A local stand-in for the Microsoft APIs that the SharePoint connector calls. Use it to:

- index a SharePoint corpus of any size without a Microsoft 365 tenant,
- count the calls and the resource units (RU) that a connector run uses,
- test throttling, delta tokens, expired download URLs and permission sync.

The server generates a tenant from a seed: sites, document libraries, folder trees, files, site
pages, users, groups and role assignments. The same settings always give the same corpus.

## What it serves

The server answers for three Microsoft hosts, each under a path prefix:

| Prefix | Host | Calls |
| --- | --- | --- |
| `/login` | `login.microsoftonline.com` | OpenID configuration, instance discovery, and `POST /{tenant}/oauth2/v2.0/token`: the client credentials grant with a client secret or a certificate assertion |
| `/graph` | `graph.microsoft.com` | Sites: `sites/getAllSites`, `sites/{hostname}:/{path}`, `sites/root`, `sites/{id}`, `sites/{id}/drives`. Drive items: `root/delta`, `children`, item by id or by path (`root:/{path}`), `content`, `permissions`, `listItem`. Site pages: the listing and one page, with and without `$expand=canvasLayout`. Directory: `groups`, `groups/{id}`, `members`, `transitiveMembers` (with the `microsoft.graph.group` and `microsoft.graph.user` casts), `users`, `users/{id}` |
| `/sharepoint/<host>` | `<tenant>.sharepoint.com` | SharePoint REST (`_api/web/...`): `RoleAssignments` of the web, a list, a list item, a folder (`GetFolderById`) and a file (`getFileByServerRelativeUrl`), `siteGroups/GetByName(...)/Users`, `getFolderByServerRelativePath`, a library (`lists/GetById(...)`, with `HasUniqueRoleAssignments`, `ItemCount` and its root folder) and its items (`lists/GetById(...)/items`, with `HasUniqueRoleAssignments`, `FileRef` and `FileDirRef`; `$filter=Id gt <n>` and `$orderby=Id` page by item id). Also the pre-authenticated download URL (`_layouts/15/download.aspx`) |

Each link in a response (`@odata.nextLink`, `@odata.deltaLink`, `webUrl`,
`@microsoft.graph.downloadUrl`, `Location`, `__next`) names the real Microsoft host, not the mock.
Thus Onyx's URL checks see what they see with Microsoft. The redirect in `patch_onyx.py` sends the
calls to the mock.

It copies Microsoft's behavior where indexing depends on it:

- **Delta.** A call without a token lists the whole drive. `token=<ISO time>` lists the items
  changed after that time. `token=latest` lists no items. The last page has an
  `@odata.deltaLink`; a later call with it lists only the items changed or deleted after that
  page. A deleted item has the `deleted` facet. `$top` and `$select` are honored. An unknown or
  expired token answers `410 Gone` with a `Location` header that starts a full enumeration.
- **Sharing facet.** With `Prefer: hierarchicalsharing`, only a permission root has the `shared`
  facet: the root of the library and each item with unique permissions. Without the header, an
  item with a sharing link has it. With `deltashowsharingchanges`, an item whose permissions
  changed after the token has `@microsoft.graph.sharedChanged`. The server echoes the
  preferences it knows in `Preference-Applied`.
- **Permissions.** A securable with no unique role assignments answers with those of its nearest
  ancestor that has them: folder, library, then web. A unique grant adds Limited Access on the
  web. A sharing link breaks inheritance and grants through a `SharingLinks.*` site group.
- **Tokens.** SharePoint REST refuses a token that came from a client secret, and a token for
  another audience. Graph refuses a token for another audience.
- **Download URLs.** The URL needs no `Authorization` header and expires. `/content` answers 302
  to a new download URL.
- **Errors.** Error bodies use the Graph shape (`{"error": {"code", "message"}}`) and the
  SharePoint REST verbose OData shape.

It does not do these things:

- It does not check signatures. An access token is not signed, and any certificate assertion
  is accepted. The client secret must match.
- It has no writes through the Microsoft APIs. Change the corpus with the control endpoints.
- It serves the commercial cloud only (`graph.microsoft.com`, `login.microsoftonline.com`,
  `*.sharepoint.com`).
- It has no Graph `$batch`, no `$filter` except `displayName eq '...'` on groups, and no OneDrive
  content: personal sites are in the site listing only.

Known differences from live Graph:

- **Site listing.** `getAllSites` does not list the root site.
- **Delta order.** Items come in the order of their last change. A full enumeration does not
  list deleted items.
- **Size.** The `size` of a generated file is the size of its source text, not the exact byte
  count. `Content-Length` is exact.
- **Throttling.** The 429 body and `Retry-After` come from Microsoft's documentation. Live
  SharePoint REST sends a different 429 body.
- **Latency.** The mock waits a base time with uniform jitter. Live latency has a long tail.
- **Download URL cost.** A download URL fetch costs 0 RU by default (`quota.download_url_ru`).
  It is refused during a pause.

## Run it

Run one worker. The corpus, the RU counts and the stats live in the process.

```bash
cd backend/tests/integration/mock_services/mock_sharepoint_server
uv run uvicorn mock_sharepoint.app:app --port 9651
```

The `/_mock` routes have no authentication, so listen on the loopback address only. When Onyx
workers run in containers, listen on an address that only they can reach.

Set the startup settings with `MOCK_SHAREPOINT_CONFIG` (a JSON object) or
`MOCK_SHAREPOINT_CONFIG_FILE` (a JSON file). See `mock_sharepoint/settings.py` for every setting.

## Corpus

`POST /_mock/corpus` merges the body into the current corpus settings and generates a new corpus.

| Setting | Default | Meaning |
| --- | --- | --- |
| `seed` | 42 | The same seed gives the same ids, names, content and permissions |
| `tenant` | `onyxmock` | The SharePoint host is `<tenant>.sharepoint.com` |
| `num_sites` | 3 | Sites `https://<host>/sites/site1` ... |
| `num_personal_sites` | 1 | OneDrive sites on `<tenant>-my.sharepoint.com` in the site listing. The connector must skip them |
| `libraries_per_site` | 2 | The first is `Documents` (URL segment `Shared Documents`), then `Library 2` ... Each has a `list` id |
| `folder_depth`, `folder_branching` | 2, 2 | Folder levels under each library root, and subfolders of each folder (`Folder 1`, `Folder 2`) |
| `files_per_folder` | 3 | Supported files (`txt`, `md`, `docx`, `pptx`, `pdf`) in each folder and each library root |
| `unsupported_files_per_library` | 2 | `.zip` and `.exe` files in each library root. The connector must skip them |
| `pages_per_site` | 3 | Site pages with a `canvasLayout` of a text web part and a standard web part |
| `corrupt_canvas_pages_per_site` | 0 | Pages whose `canvasLayout` expansion answers 400. The expanded page listing then answers 400 too |
| `num_users`, `num_security_groups`, `num_m365_groups` | 8, 3, 1 | Entra users and groups. The first security group holds the second one and a distribution list |
| `unique_permission_fraction` | 0.15 | Share of files and folders with broken inheritance |
| `public_fraction` | 0.1 | Share of those that grant read to "Everyone except external users" |
| `sharing_link_fraction` | 0.05 | Share of files with a sharing link (`anonymous`, `organization` or `users`) |
| `extension_weights` | | Relative weights of the supported extensions |
| `avg_content_bytes`, `max_content_bytes` | 1,500, 20,000 | Sizes follow a log-normal spread around the average |
| `base_time` | 2025-06-01 12:00 UTC | Created and modified times are in the 30 days before it |

Each site has the site groups `<Site> Owners`, `<Site> Members` and `<Site> Visitors` with Full
Control, Edit and Read on the web. Their members are users, security groups and a Microsoft 365
group. User principal names end in `<tenant>.onmicrosoft.com`. Onyx removes `.onmicrosoft` from
them, and the control endpoints give the addresses that Onyx stores.

## Resource units and throttling

The server counts RU for each app. An app is a (tenant id, client id) pair, read from the access
token. The token endpoint accepts any client id, so a test can run more than one app.

| Call | RU | Setting |
| --- | --- | --- |
| Get one item | 1 | `item_get_ru` |
| Delta with a token (a next link also has one) | 1 | `delta_with_token_ru` |
| Delta without a token | 2 | `delta_without_token_ru` |
| `/content` | 1 | `download_ru` |
| Download URL | 0 | `download_url_ru` |
| List children | 2 | `list_children_ru` |
| Graph permissions of an item | 5 | `permission_ru` |
| SharePoint REST call | 2 | `rest_ru` |
| Any other Graph call (sites, drives, site pages, groups) | 1 | `other_ru` |

Sign-in calls cost nothing. The other `quota` settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `enabled` | true | false stops the limits. The stats still count the RU |
| `ru_per_minute`, `window_seconds` | 1,250, 60 | The limit in a sliding window. A shorter window scales the limit |
| `ru_per_day`, `day_window_seconds` | none, 86,400 | An optional second limit |
| `throttle_status` | 429 | 429 or 503 |
| `retry_after_seconds` | 10 | The `Retry-After` value and the length of the pause. `null` sends no header and starts no pause |
| `count_throttled_calls` | true | A throttled call also uses its RU |

A call over a limit answers `throttle_status` with `Retry-After` and the Graph error body. The
code is `TooManyRequests` (`activityLimitReached` for the daily limit, `serviceNotAvailable` for
503). SharePoint REST calls answer the same way.

The throttled call starts a pause for its app. Until the pause ends, the server refuses every
Graph and REST call of that app with the time that is left in `Retry-After`. The stats count these
calls in `calls_during_pause`. A client that obeys `Retry-After` has a count of 0. A download URL is
not a Graph call: the Graph limits and the pause do not apply to it.

## Latency and faults

| Setting | Default | Meaning |
| --- | --- | --- |
| `latency.enabled` | true | Each call waits a base time (`token_ms`, `metadata_ms`, `list_ms`, `content_ms`, `rest_ms`, `throttled_ms`) with `jitter`, plus its body size over `bandwidth_bytes_per_second` |
| `faults.server_error_rate` | 0 | Share of Graph and SharePoint calls that fail with a 500 or 503 |
| `faults.expire_delta_tokens` | false | Each delta link and each timestamp token answers 410. `token=latest`, a call without a token and its next links still work |
| `faults.download_url_ttl_seconds` | 3600 | Life of a download URL. 0 gives a URL that is always expired |
| `faults.download_url_expired_status` | 401 | 401 or 403 |
| `faults.content_redirect` | true | `/content` answers 302 to a download URL that is valid for 300 seconds. false sends the bytes |
| `auth.rest_requires_certificate` | true | SharePoint REST refuses a client secret token |
| `auth.client_id`, `auth.client_secret`, `auth.certificate_password` | | The app of `GET /_mock/credentials` |
| `paging.*` | | Page sizes of the listings whose callers send no `$top` |

For example:

```bash
# A tight budget, to see the connector under throttling
curl -X PATCH localhost:9651/_mock/config -H 'content-type: application/json' \
  -d '{"quota": {"ru_per_minute": 200, "retry_after_seconds": 5}}'

# No latency: shows the connector's own processing limit
curl -X PATCH localhost:9651/_mock/config -H 'content-type: application/json' \
  -d '{"latency": {"enabled": false}}'
```

## Control endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /_mock/stats`, `POST /_mock/stats/reset` | Calls since the last reset. The reset also clears the RU counts and each pause |
| `GET /_mock/config`, `PATCH /_mock/config` | Read or change the `quota`, `latency`, `auth`, `paging` and `faults` settings |
| `POST /_mock/corpus` | Generate a new corpus from corpus settings. Resets the stats and the hooks |
| `GET /_mock/corpus/summary?include_ids=true` | Counts, site URLs and, with ids: `drive_ids`, `drive_web_urls`, `supported_file_ids`, `unsupported_file_ids`, `page_ids`, `folder_ids`, `folder_web_urls`, `unique_permission_item_ids`, `sharing_link_item_ids` |
| `GET /_mock/corpus/files/{id}` | One file or folder as stored, with its `web_url`, `path`, `role_assignments` and `effective_access` |
| `GET /_mock/corpus/pages/{id}` | One site page, with the same access fields |
| `GET /_mock/corpus/sites` | Each site with its libraries, the access of the site and library nodes, its site groups and `expected_external_groups`. Also the Entra groups and users |
| `POST /_mock/corpus/touch` | Mark files as modified now: `{"file_ids": [...]}` or `{"count": N}` random files |
| `POST /_mock/corpus/files` | Add a file: `{"drive_id", "name", "parent_id" or "folder_path", "text"}` |
| `DELETE /_mock/corpus/files/{id}` | Delete a file, or a folder with what is under it |
| `POST /_mock/corpus/permissions` | Break or restore inheritance on an item, a page or a library (see below) |
| `POST /_mock/corpus/write-during-walk`, `GET` the same path | Set a change that the server makes during a walk, and list the hooks (see below) |
| `POST /_mock/corpus/expire-delta-tokens` | Make each delta link and next link issued until now answer 410 |
| `GET /_mock/credentials` | The SharePoint credential in both forms: `client_secret` and `certificate` (a self-signed PFX) |

`effective_access` is what Onyx's permission sync must store for the securable:
`{"user_emails", "group_ids", "is_public"}`. A user with a direct grant is listed by email. A
group is listed by the name Onyx stores, in lower case, with each group inside it: a site group
as `<site url>::<name>` and an Entra group as its id. Limited Access grants nothing, and
"Everyone except external users" makes the securable public.

Set permissions:

```bash
curl -X POST localhost:9651/_mock/corpus/permissions -H 'content-type: application/json' -d '{
  "item_id": "<file or folder id>",
  "copy_parent": false,
  "grants": [
    {"principal": {"kind": "user", "key": "user1@onyxmock.com"}, "role": "read"},
    {"principal": {"kind": "entra_group", "key": "Security Group 1"}, "role": "edit"},
    {"principal": {"kind": "site_group", "key": "Site1 Visitors"}, "role": "read"},
    {"principal": {"kind": "everyone"}, "role": "read"}
  ]
}'
```

Name the securable with one of `item_id`, `page_id` and `drive_id` (the library).
`"inherit": true` restores inheritance. The roles are `limited`, `read`, `contribute`, `edit` and
`full_control`.

Write a file during a walk:

```bash
curl -X POST localhost:9651/_mock/corpus/write-during-walk -H 'content-type: application/json' -d '{
  "drive_id": "<drive id>",
  "op": "children",
  "after_calls": 3,
  "action": "create",
  "file": {"drive_id": "<drive id>", "folder_path": "Folder 1", "name": "Late.txt", "text": "late"}
}'
```

The server makes the change after it builds the answer of the Nth `children` (or `delta`) call
on that drive, counted from when the hook is set. Thus that answer does not show the change. A
`/children` walk that already listed the folder does not see the file, and a delta call from a
cursor saved before the walk does. `action` is `create` (with `file`), `modify` or `delete`
(with `file_id`).

## Stats

`GET /_mock/stats` gives, since the last reset:

- `ops`: for each operation its `count`, `throttled`, `errors`, `ru`, `bytes`, `avg_ms` and
  `canvas_expanded` (calls with `$expand=canvasLayout`). The operation names are:
  `login.openid_configuration`, `login.instance_discovery`, `login.token`, `graph.sites.list`,
  `graph.site.get`, `graph.site.drives`, `graph.site.pages.list`, `graph.site.page.get`,
  `graph.drive.get`, `graph.drive.delta`, `graph.drive.children`, `graph.item.get`,
  `graph.item.content`, `graph.item.permissions`, `graph.item.list_item`, `graph.groups.list`,
  `graph.group.get`, `graph.group.members`, `graph.group.transitive_members`, `graph.users.list`,
  `graph.user.get`, `rest.web.get`, `rest.role_assignments`, `rest.site_group_users`,
  `rest.folder.get`, `rest.list.get`, `rest.list.items`, `download_url.get`, and `graph.unmatched`, `rest.unmatched`,
  `login.unmatched` for a call with no route.
- `ru`, `ru_by_app`, `ru_per_minute` and `quota_window` (the RU in the current windows and the
  seconds left of each pause).
- `throttled`, `throttled_by_app`, `calls_during_pause` (for each app) and
  `calls_during_pause_total`.
- `item_downloads`: for each file, how many times the server sent its whole content.
- `user_agents`, `statuses`, `max_inflight`, `avg_inflight` and `unmatched_requests`.

An app key is `<tenant id>/<client id>`.

## Point Onyx at it in a test

`point_onyx_at_mock(url)` in `mock_sharepoint/patch_onyx.py` is a context manager that sends the
Microsoft calls of the test process to the mock. It changes no Onyx code and no Onyx setting. It
patches `requests.Session.send`, which MSAL, the office365 SDK and Onyx's Graph calls all use, and
`socket.getaddrinfo` for `*.sharepoint.com` names, because the mock tenant has no DNS record.

The fixtures in `backend/tests/external_dependency_unit/connectors/sharepoint/conftest.py` use it:

- `mock_sharepoint`: the module's shared server. Do not change its corpus or config.
- `own_mock_sharepoint`: a server for one test.
- `ee_permission_sync`: turns on the Enterprise permission code.

Both give a `MockSharepoint` with `build_connector(certificate=False, **kwargs)`, `stats()`,
`reset_stats()`, `patch_config()`, `set_corpus()` and helpers for the corpus. Permission sync
needs `certificate=True`. `start_mock_server(config)` in `mock_sharepoint/runner.py` starts a
server on a free port for a script.

```bash
uv run pytest backend/tests/external_dependency_unit/connectors/sharepoint
```

These tests need no database.

## Point a running Onyx at it

Onyx has no setting for this. `sitecustomize.py` in this directory installs the same patches at
process start, when `MOCK_SHAREPOINT_URL` is set.

1. Start the API server and every Celery worker with this directory on `PYTHONPATH` and
   `MOCK_SHAREPOINT_URL` set, for example:

   ```bash
   export PYTHONPATH="$PWD/backend/tests/integration/mock_services/mock_sharepoint_server:$PYTHONPATH"
   export MOCK_SHAREPOINT_URL=http://localhost:9651/
   ```

   Python imports `sitecustomize` once, from the first directory on the path that has one. When
   it is set, every call of the process to Graph, to Entra sign-in or to a SharePoint host goes
   to the mock. This includes the Teams, OneDrive and Outlook connectors, and the mock has no
   routes for their calls, so they fail.
2. Get the credential: `curl -s localhost:9651/_mock/credentials`
3. In the Admin panel, add a SharePoint connector. Enter `sp_client_id`, `sp_directory_id` and
   `sp_client_secret` from the `client_secret` form. For permission sync, use the `certificate`
   form: decode `sp_private_key` from base64 to a `.pfx` file and upload it with
   `sp_certificate_password`.
4. Leave the sites empty to index every site, or enter site URLs from
   `curl -s localhost:9651/_mock/corpus/summary`.
