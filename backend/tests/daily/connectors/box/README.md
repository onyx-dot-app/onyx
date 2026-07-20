# Box Connector Test Setup

How to provision a Box test enterprise so the daily tests in this directory
(`test_box_basic.py`) pass. The tests assert against the exact corpus
defined below — names and file contents must match character-for-character.

The unit tests under `backend/tests/unit/onyx/connectors/box/` need none of
this; they run fully offline.

## Incremental indexing (how the connector polls)

Box's folder-listing API (`GET /folders/:id/items`) has no server-side
modified-time filter, so a naive poll would re-list the entire corpus every
run. The connector avoids that:

- **First index, folder-scoped connectors, pruning, and permission sync** do a
  full BFS crawl of the folder tree.
- **Steady-state whole-enterprise polls** (poll window ≤ 7 days) instead consume
  the Box enterprise **events stream** (`GET /events?stream_type=admin_logs`,
  filtered to content-change event types) and re-index only the files that
  actually changed. The queried window is delayed by 24 hours because Box warns
  that historical admin-log events can arrive after a near-real-time filter
  window has already been read.
- A window wider than 7 days (e.g. a long outage) falls back to a full crawl,
  which doubles as periodic reconciliation. If the events API errors (e.g.
  missing admin scope) the run falls back to a full crawl rather than indexing
  nothing. Folder move/rename events also trigger a full crawl because they can
  change the paths of every descendant.
- Connectors that index Box web links always use full crawls because enterprise
  event sources only identify files and folders.
- Deletions are reconciled by the slim-based pruning job, not the events path
  (the events path only re-indexes changed/added files).

There is no daily test for the events path — admin-log ingestion lag makes a
synchronous live assertion flaky — but it's covered comprehensively offline in
`backend/tests/unit/onyx/connectors/box/test_box_events.py`.

## 1. Create a Box developer account

Sign up at <https://developer.box.com> (free). This provisions a sandbox
enterprise where you are the admin, with access to the Admin Console and the
Developer Console.

A regular box.com **Individual/Free account is not a developer account** and
cannot be converted into one — it has no enterprise behind it, so
`App + Enterprise Access`, CCG, the Admin Console, managed users, and groups
are all unavailable (the Developer Console fails with "some of your settings
could not be saved"). Use the developer signup path with a fresh email, or a
Box Business trial, or a developer sandbox issued from a paid Box enterprise.

## 2. Create the Platform App (CCG)

1. In the [Developer Console](https://app.box.com/developers/console), create
   **Platform App → Custom App**.
2. Choose **Server Authentication (Client Credentials Grant)**.
3. On the app's **Configuration** tab:
   - **App Access Level**: `App + Enterprise Access`
   - **Application Scopes**: enable
     - `Read all files and folders stored in Box`
     - `Manage users` (group sync enumerates enterprise users)
     - `Manage groups` (group sync enumerates groups and memberships)
   - **Advanced Features**: enable `Generate user access tokens`
     (the connector impersonates a user via `box_user_email`)
4. Save changes, then on the **Authorization** tab click **Review and Submit**.
5. In the **Admin Console → Apps → Custom Apps Manager**, approve the pending
   app authorization. Re-approve after any scope change — scope edits do not
   take effect until reauthorized.

Collect from the Configuration tab:

- **Client ID**
- **Client Secret** — the "Fetch Secret" button requires the Box account to be
  **enrolled in two-factor authentication** first (it silently no-ops
  otherwise, and the underlying request returns `two_fa_enrollment_required`).
  Enroll 2FA under account Settings, then fetch the secret.
- **Enterprise ID** (also on the app's General Settings tab)

## 3. Create the users

1. Your own admin account is the **primary user**. Its login (email) is
   `BOX_USER_EMAIL` — the connector impersonates this user (resolving the email
   to a Box user ID via the Manage-users scope), so the test corpus lives in
   this user's "All Files".
2. Create a second **managed user** (`POST /users` with a `login` + `name`, or
   Admin Console → Users & Groups → Add User). It only needs to exist; nobody
   logs in as it. Its login is `BOX_COLLABORATOR_EMAIL`. Note Box rejects
   collaborations to a **deactivated** user with `cannot_invite_deactivated_user`
   — if the login you want is already taken by a deactivated account, use a
   distinct login (a `+alias` on the same inbox works, e.g.
   `oauth+box@onyx.app`).

## 4. Create the test corpus

Create, in the primary (impersonated) user's **All Files**:

```
Onyx Connector Test Folder/
├── root_doc.txt        content: box root doc for onyx connector tests
├── public_doc.txt      content: public doc for onyx connector tests
├── editor_doc.txt      content: editor doc for onyx connector tests
├── Onyx Example Link   web link (bookmark) -> https://www.onyx.app
│                       description: example bookmark for onyx connector tests
├── Subfolder A/
│   └── alpha.txt       content: alpha doc for onyx connector tests
├── Shared Folder/
│   └── shared.txt      content: shared doc for onyx connector tests
└── Uploader Folder/
    └── uploader_doc.txt  content: uploader doc for onyx connector tests
```

The corpus exercises **multiple share levels** for the collaborator user, which
is the point of the perm-sync assertions:

| Item                | Collaboration / link            | Collaborator can read? |
| ------------------- | ------------------------------- | ---------------------- |
| `Shared Folder`     | folder-level **Viewer**         | yes (→ `shared.txt`)   |
| `editor_doc.txt`    | file-level **Editor**           | yes                    |
| `Uploader Folder`   | folder-level **Uploader**       | **no** (upload-only)   |
| `public_doc.txt`    | **open** shared link            | public                 |
| everything else     | none                            | owner-only             |

Details that matter:

- Create the files as real `.txt` uploads (write them locally and drag them
  in). Box Notes are a different file type and will not extract to the expected
  text. A trailing newline is fine; the tests strip it.
- The **Uploader** collaboration is a deliberate negative case: `uploader` is
  Box's upload-only role, so the connector must NOT grant it read access.
  `uploader_doc.txt` is still indexed (the owner can read it), but the
  collaborator must be absent from its access set.
- Invites to managed users in the same enterprise auto-accept; confirm each
  collaboration is active, not pending.
- `public_doc.txt`: shared link access **"People with the link"** (the `open`
  level), no password.
- Do **not** add a shared link or collaborations to `Onyx Connector Test
  Folder` itself, `Subfolder A`, `root_doc.txt`, or `alpha.txt` — the tests
  assert those are owner-only.
- `Onyx Example Link` is a **web link** (bookmark), not a file: create it in the
  root test folder pointing to `https://www.onyx.app` with the description
  above. It's only indexed when the connector's `include_web_links` is on, as a
  thin bookmark document (name + description as text; the linked page is not
  fetched).

Then create a group named exactly `Onyx Test Group` and add the collaborator
user as a member. Do not collaborate this group onto any folder; it exists only
to exercise group sync.

> Fastest way to build all of the above is the Box API with a developer token
> (Developer Console → your app → **Developer Token**): `POST /folders`,
> `POST /files/content` (upload host), `POST /web_links` (the bookmark),
> `POST /collaborations` (one per level), `PUT /files/:id` with
> `shared_link.access=open`, `POST /groups` + `POST /group_memberships`.

## 5. Provide the secrets

The test secrets resolve in order: process environment variables → the repo's
`.vscode/.env` → AWS Secrets Manager. Names:

| Env var (local runs)      | AWS Secrets Manager key (CI)  | Value                          |
| ------------------------- | ----------------------------- | ------------------------------ |
| `BOX_CLIENT_ID`           | `test/box-client-id`          | app Client ID                  |
| `BOX_CLIENT_SECRET`       | `test/box-client-secret`      | app Client Secret              |
| `BOX_ENTERPRISE_ID`       | `test/box-enterprise-id`      | Enterprise ID                  |
| `BOX_USER_EMAIL`          | `test/box-user-email`         | primary (admin) user's email   |
| `BOX_COLLABORATOR_EMAIL`  | `test/box-collaborator-email` | collaborator user's email      |

For CI, create the five secrets under the `test/` prefix in AWS Secrets
Manager (us-east-2), e.g.:

```bash
aws secretsmanager create-secret --region us-east-2 \
  --name test/box-client-id --secret-string "<client id>"
```

## 6. Run the tests

```bash
source .venv/bin/activate
export BOX_CLIENT_ID=... BOX_CLIENT_SECRET=... BOX_ENTERPRISE_ID=... \
       BOX_USER_EMAIL=... BOX_COLLABORATOR_EMAIL=...
pytest -xv backend/tests/daily/connectors/box
```

For ad-hoc manual exploration without pytest, the connector has a dev entry
point (add `BOX_FOLDER_IDS=<id>` to scope it):

```bash
PYTHONPATH=backend python backend/onyx/connectors/box/connector.py
```

## What the tests assert (summary)

- `test_load_documents` — the six documents (by name, extracted content,
  `path` metadata, UTC timestamps, owner email, `app.box.com` links) and the
  four folder hierarchy nodes.
- `test_web_links` — with `include_web_links` on, the `Onyx Example Link`
  bookmark is indexed as a `box-weblink-*` document whose section links to the
  target URL and whose text carries the name + description.
- `test_poll_window_filters_documents_but_not_hierarchy` — a 1970 poll window
  yields no documents but still yields the folder tree.
- `test_perm_sync_external_access` — across the share matrix: `shared.txt`
  (folder Viewer) and `editor_doc.txt` (file Editor) grant the collaborator;
  `uploader_doc.txt` (folder Uploader) does NOT (upload-only role);
  `root_doc.txt` is owner-only; `public_doc.txt` is public via its open link.
- `test_group_sync` — `Onyx Test Group` syncs with the collaborator as a
  member, and the synthetic `box-enterprise-all-users` group contains every
  managed user.
- `test_validate_connector_settings` — valid credentials pass validation and
  the perm-sync probes; a nonexistent folder ID fails with a validation error.
