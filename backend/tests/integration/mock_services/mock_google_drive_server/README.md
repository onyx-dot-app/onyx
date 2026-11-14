# Mock Google Drive server

A local stand-in for the Google APIs that the Google Drive connector calls. Use it to:

- index a Drive corpus of any size without a Google Workspace,
- measure connector throughput against Google's quotas,
- test rate limits, server errors and domain-wide delegation failures.

The server generates a Workspace from a seed: users, groups, shared drives, folder trees,
files, shares and shortcuts. The same settings always give the same corpus.

## What it serves

| API | Calls |
| --- | --- |
| OAuth | `POST /token`: the service-account JWT grant (with domain-wide delegation) and the refresh-token grant |
| Drive v3 | `files.list` (with `q`, `corpora`, `orderBy`, `pageSize`, `fields`), `files.get`, `files.get?alt=media` (with `Range`), `files.export`, `permissions.list`, `permissions.get`, `drives.list`, `drives.get`, `about.get`, batch requests |
| Admin SDK Directory | `users.list`, `users.get`, `groups.list`, `members.list` |
| Docs v1 | `documents.get` (with `includeTabsContent`) |

It copies Google's behavior where indexing depends on it:

- **Visibility.** A user sees files they own, files shared with them or their groups, and the
  files of shared drives they are a member of. `parents` lists only parents the user can see.
- **Permissions.** `permissions` is filled only for a user who can share the item, and never for
  shared drive items. A shared drive item lists the drive's members as inherited permissions.
- **Errors.** Error bodies use Google's shapes and reasons, for example `notFound`,
  `userRateLimitExceeded`, `rateLimitExceeded`, `fileNotDownloadable` and `unauthorized_client`.
- **Content.** Google Docs, Sheets and Slides export as text, Markdown, HTML, PDF, DOCX, CSV, TSV
  or PPTX. Uploaded PDF, DOCX, PPTX, text and Markdown files download as themselves.

It does not do these things:

- It does not check JWT signatures. Any key with the configured `client_email` works.
- It has no writes, uploads, Changes API or revisions.
- The `size` of an uploaded file is the target text size, not the exact byte count.

Known differences from live Drive:

- **Page fill.** The mock fills each `files.list` page to `pageSize`. Live Drive returns fewer
  files than asked (see below).
- **Latency.** The mock waits a base time with uniform jitter. Live latency has a long tail.
- **Rate limit bodies.** The 429 and `Retry-After` shapes come from Google's documentation. We
  did not see them live yet.
- **Folder sharing.** A share on a folder does not pass to its children.

## Verified against live Drive

We checked these on the onyx.app Workspace on 2026-11-12 and 2026-11-13:

- `files.list` pages with `orderBy=modifiedTime` come back in `modifiedTime` order
  (2,375 of 2,375 pages).
- `modifiedTime` bounds in `q` honor milliseconds.
- A bulk upload stores one whole-second `modifiedTime` for each file. One burst had 3,125 files at
  `07:58:00.000`, and more bursts followed about 2 seconds apart.
- A lean listing page (no permission fields) holds about 460 files when 1,000 are asked. The
  mock fills the page to 1,000.
- A page with permission fields holds about 100 files.
- External accounts (`gmail.com`) own a large set of files that is shared with several domain
  users. Each user gets the same set.

## Run it

Run one worker. The corpus, quotas and stats live in the process.

```bash
cd backend/tests/integration/mock_services/mock_google_drive_server
uv run uvicorn mock_gdrive.app:app --port 9650 --timeout-keep-alive 120
```

Or build the image:

```bash
docker build -t mock-google-drive backend/tests/integration/mock_services/mock_google_drive_server
docker run -p 127.0.0.1:9650:9650 mock-google-drive
```

The `/_mock` routes have no authentication, so publish the port on the loopback address only.
When Onyx workers run in containers, publish it on an address that only they can reach.

Set the startup settings with `MOCK_GDRIVE_CONFIG` (a JSON object) or `MOCK_GDRIVE_CONFIG_FILE`
(a JSON file). See `mock_gdrive/settings.py` for every setting.

## Corpus shapes

These corpus settings are off by default. They add files after the default corpus, from a
separate random stream, so the rest of the corpus does not change. The same seed gives the same
files.

| Setting | Meaning |
| --- | --- |
| `external_shares.owners` | External accounts `ext1@<owner_domain>` ... that own files. They are not users: the directory does not list them, and the token endpoint refuses to impersonate them (`invalid_grant`), as Google does. |
| `external_shares.owner_domain` | Domain of the external accounts. Default `gmail.com`. |
| `external_shares.files` | Files owned by the external accounts, spread over them. |
| `external_shares.recipients` | The first N non-admin users. Each one gets a reader share on every external file. |
| `bulk_uploads[].count` | Files in each burst. Every file in a burst has one whole-second `modifiedTime`. |
| `bulk_uploads[].bursts`, `spacing_seconds` | Number of bursts, and the seconds between them. |
| `bulk_uploads[].start` | Time of the first burst. Default `2025-06-01T07:58:00Z`. |
| `bulk_uploads[].container`, `index` | `my_drive` of user `index` (0 is the admin), `shared_drive` `index`, or `external` account `index` (shared with the `external_shares` recipients). |
| `folder_trees[].container`, `index` | `my_drive` of user `index` or `shared_drive` `index`. |
| `folder_trees[].depth`, `branching` | Folder levels under the tree's root folder, and subfolders of each folder. |
| `folder_trees[].files_per_folder` | Files in each folder of the tree. |
| `folder_trees[].deepest_folder_files` | More files in the first folder of the last level: a large folder deep in the tree. |

For example:

```bash
curl -X POST localhost:9650/_mock/corpus -H 'content-type: application/json' -d '{
  "external_shares": {"owners": 2, "files": 500, "recipients": 3},
  "bulk_uploads": [{"count": 3125, "bursts": 3, "spacing_seconds": 2, "container": "external"}],
  "folder_trees": [{"container": "shared_drive", "depth": 5, "deepest_folder_files": 2000}]
}'
```

`POST /_mock/corpus` merges the body into the current corpus settings. A nested object, such as
`mime_weights`, merges key by key: set a weight to 0 to remove a type.

The corpus summary lists `external_owner_emails`, `external_recipient_emails` and
`folder_tree_root_ids`.

## Measure connector throughput

The benchmark runs the connector's checkpoint loop in one process, the way docfetching does. It
reports docs per minute, the quota the run used, the requests in flight, and every file that did
not become a document.

```bash
cd backend
uv run python -m scripts.benchmark_google_drive_connector --mock-url http://localhost:9650
```

The run needs no database or file store: it stages spreadsheets in memory and extracts text
without the Unstructured API. Add `--start-mock` to start a mock server for the run only.

Useful scenarios:

```bash
# A larger corpus (about 30,000 files)
--corpus '{"num_users": 20, "files_per_user": 1000, "num_shared_drives": 10, "files_per_shared_drive": 1000}'

# No latency: shows the connector's own processing limit
--config '{"latency": {"enabled": false}}'

# The legacy quota model: 12,000 requests per minute per project and per user
--config '{"quota": {"model": "requests"}}'

# A tight per-user quota, answered with 403 userRateLimitExceeded
--config '{"quota": {"user_units_per_minute": 20000, "retry_after_seconds": 2}}'

# Random 500 and 503 answers
--config '{"faults": {"server_error_rate": 0.05}}'

# Fetch permissions during indexing, as an EE connector with sync access does
--perm-sync

# Override the connector's tunables for the run
--conversion-workers 16 --partitions-per-checkpoint 8

# Write cProfile stats of every thread (read them with pstats)
--profile /tmp/drive.pstats
```

Read the report like this:

- **Docs per minute** is what the connector reached.
- **Quota units/min** compares the run's use with the project quota. A low share means the
  connector, not Google, limits throughput.
- **Concurrency** is the average and the most requests in flight. By Little's law, docs per
  second is about the requests in flight divided by the time per document.
- **Missing (without a failure)** counts files that the run dropped without a `ConnectorFailure`.
  A later run does not retry these files. The benchmark measures it only for a crawl of every
  scope that runs to its end, with no `--no-…` scope flag and no `--max-docs` stop.
- **CPU** is the benchmark process's CPU seconds, whose threads share one GIL, and the PDF
  subprocesses'. When the process's CPU seconds come close to the elapsed seconds, parsing in
  the process limits the run, and more workers do not help.

## Point a running Onyx at it

1. Add `GOOGLE_API_ENDPOINT_OVERRIDE=http://localhost:9650/` to the environment of the API server
   and every Celery worker, for example in `.vscode/.env`. Then restart them. The setting is for
   testing only. When it is set, every Google connector sends its calls to the mock. This
   includes Gmail connectors, and the mock has no Gmail routes, so their calls fail.
2. Save the service account key:
   `curl -s localhost:9650/_mock/service-account-key > mock-service-account.json`
3. In the Admin panel, add a Google Drive connector. Upload `mock-service-account.json` as a
   service account and enter `admin@onyx-mock.test` as the primary admin email.

To reproduce Google's domain-wide delegation error, grant fewer scopes than the connector asks for:

```bash
curl -X PATCH localhost:9650/_mock/config -H 'content-type: application/json' \
  -d '{"faults": {"granted_scopes": ["https://www.googleapis.com/auth/drive.readonly"]}}'
```

## Control endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /_mock/stats`, `POST /_mock/stats/reset` | Calls, units, rate limits, latency and requests in flight since the last reset |
| `GET /_mock/config`, `PATCH /_mock/config` | Read or change the quota, latency and fault settings |
| `POST /_mock/corpus` | Generate a new corpus from corpus settings; resets the stats |
| `GET /_mock/corpus/summary?include_ids=true` | Counts, users, shared drives and the ids of every content file |
| `GET /_mock/corpus/files/{id}` | One file as stored, with the users who can read it |
| `GET /_mock/corpus/folders/{id}/content-ids` | The content files under a folder at any depth: what a folder target must index |
| `GET /_mock/corpus/users/{email}/content-ids?scope=` | The content files a user lists: `all_drives` (what `corpora=allDrives` returns), `owned` or `shared_with_me`. What an OAuth connector of that user must index |
| `POST /_mock/corpus/touch` | Mark files as modified now, for incremental runs |
| `GET /_mock/service-account-key` | A service account key for the mock |
| `GET /_mock/oauth-credentials?email=` | An OAuth token for one domain user (404 for anyone else). Upload it as an OAuth credential with that user as the primary admin |
