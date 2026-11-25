# Windows File Share (SMB)

> The Windows file share connector indexes the files of one SMB share, with
> `smb://<host>/<share>/<path>` as the document id. Every run walks the whole
> folder tree, because SMB has no recursive listing and no change feed.

**Verified against:** `e8c6f1dd0a` (2026-11-25)
**Edition:** CE. EE syncs each file's NTFS access list as document readers and
Active Directory groups as external groups
(`ee/onyx/external_permissions/smb/`).

---

## User experience

An admin enters a file server, a share and an optional path prefix, with a
domain service account. Onyx indexes the files the account can read, shows the
folder tree, picks up changed files on each poll and prunes deleted files. A
document has no link, because a browser blocks file links. Its UNC path is in
the `path` metadata. A folder that the account may not list is left out with
no error. The source is refused on a multi-tenant deployment, and a file
server on a private network needs a lowered SSRF protection level.

With EE permission sync, a user sees a file when the file's NTFS access list
lets the user in. The admin must confirm that the share permissions are not
narrower than the NTFS permissions, or the sync does not run. A file that only
local groups of the file server can read is visible to nobody.

---

## Scope

This document holds the rules of the SMB connector: the walk and its
checkpoint, the poll window, the network policy on each server a session
reaches, and how an NTFS access list becomes readers. Its neighbours own:
- [[connectors]]: the interfaces, gateway and prune contracts.
- [[connector-capability-checks]]: the check runner. This connector registers
  named checks for indexing and for both syncs.
- [[permission-sync]]: the doc sync and group sync tasks that call this
  connector's access walk and group listing.
- [[microsoft-graph]]: a false lead. Active Directory is read over LDAP in this
  connector's gateway, not through Graph. Only the principal set code is shared
  with the Azure Data Lake permission sync.

---

## Architecture

**Walk and checkpoint.** `connectors/smb/connector.py:SmbConnector.load_from_checkpoint`
lists one folder per step, sorts the names, and reads at most
`connectors/smb/connector.py:FILES_PER_STEP` files. `SmbCheckpoint` holds
a stack of folders still to walk, the current folder and the last name done in
it. A resumed step lists the folder again and continues after that name. The
listing carries each entry's attributes and timestamps, so the walk makes no
request per file.

**Poll window.** A file is in the window by the newest of its creation, last
write and change time (`connectors/smb/models.py:SmbEntry.changed_at`). A
copied file keeps its old last write time, and a rename changes only the
change time.

**Gateway.** `connectors/smb/source_operations.py` holds every SMB and LDAP
call. Each gateway has its own smbclient connection cache, so two credentials
for one server never share a session.

**Access.** The CE connector reaches EE through `connectors/smb/access.py`.
`external_permissions/smb/acl.py:dacl_readers` reads the access list in stored
order into a principal set, and `external_permissions/smb/access.py` resolves
it to emails, group SIDs and exclusion groups.

---

## Contracts and traps

1. `policy-on-every-server` **The network policy covers each server a session
   reaches, not only the configured host.** smbclient follows a DFS referral to
   another server and signs in there with the same account.
   `connectors/smb/source_operations.py:_PolicedConnectionCache` checks a
   server before the connection and the address the socket reached before the
   sign-in. It depends on the order in which `smbclient.register_session` reads
   and writes the cache, so check it when the pinned `smbprotocol` changes. The
   LDAP connection does not follow referrals for the same reason.
2. `slim-walk-raises` **The slim walk raises on each listing error except a
   refused one.** A folder left out by mistake loses its documents to pruning,
   and an unchanged file is not indexed again by a later poll.
   `connectors/smb/connector.py:SmbConnector._list_sorted` takes
   `quiet_missing` for the indexing walk only.
3. `rename-has-no-file-timestamp` **A renamed folder gives its files new
   document ids and no new timestamp.**
   `connectors/smb/connector.py:moved_since` decides from the folder's change
   time and its parent's last write time, and the walk then indexes all files
   below. Neither time has an upper bound: a later change can move both past
   the end of the window.
4. `builtin-sids-are-local` **A BUILTIN SID is never looked up in the
   domain.** A domain controller lists its own BUILTIN groups under the same
   SIDs as the file server's local groups.
   `external_permissions/smb/acl.py:classify` looks up only SIDs of the
   domain.
5. `unknown-deny-is-private` **A deny entry for a principal Onyx cannot name
   makes the file private.** An allow entry for such a principal grants
   nothing. Both fail closed (`external_permissions/smb/acl.py:dacl_readers`).
6. `never-public` **No access list makes a document public.** Everyone,
   Authenticated Users and Domain Users map to the synced group of the domain's
   users (`external_permissions/smb/directory.py:ActiveDirectory.everyone_group_id`).
7. `share-permissions-not-read` **Permission sync reads NTFS permissions
   only.** The share's own access list needs an RPC that `smbprotocol` does not
   have. The `share_permissions_confirmed` config field records the admin's
   statement, and the check that reads it also runs before each sync
   (`ee/onyx/connectors/perm_sync_valid.py:validate_smb_perm_sync`).
8. `security-descriptor-uses-internals` **The access list read uses smbclient
   internals.** `connectors/smb/source_operations.py:SmbSourceOperations.read_security_descriptor`
   builds a compound request with `smbclient._io`. The `smbprotocol` version is
   pinned for it.
9. `exclusion-ids-are-lowercase` **Stored group ids are in lower case, SIDs in
   code are in upper case.** `external_permissions/smb/exclusion_groups.py:parse_exclusion_group_id`
   restores the case of the SIDs it reads back.
10. `kerberos-settings-are-process-wide` **Kerberos settings are one file for
   the process.** The Kerberos library reads its settings from files, so
   `connectors/smb/kerberos_config.py:register_realm` writes each realm a
   credential names into one file and puts it first in `KRB5_CONFIG`. The
   first credential to name a realm or a server decides its entry, also when
   it names no KDC host, and a later one that differs is refused until the
   process restarts.
   The file holds the KDC addresses that passed the network policy, and turns
   off the KDC lookup through DNS. The values are checked before they are
   written, because they come from a credential and go into a settings file.
11. `kerberos-libraries-are-optional` **The Kerberos libraries are in the
   backend image only.** `gssapi` and `krb5` compile against system headers, so
   they are in the `kerberos` dependency group and outside the default groups.
   `connectors/smb/source_operations.py:_kerberos_library` loads them by name
   and gives a clear error where they are absent. Do not import them at the
   top of a module.

---

## Known issues

- A server that keeps no separate change time reports the last write time in
  its place. Samba does this. A file or folder renamed on such a server is not
  indexed under its new name until its content changes or a full re-index runs.
- A link that the server itself follows shows as a plain folder. Only
  `connectors/smb/connector.py:MAX_FOLDER_DEPTH` ends such a loop, and the
  files in the loop are indexed once per level until then.
- smbprotocol waits for a response with no time limit. TCP keepalive closes a
  connection whose peer stopped answering.
- Scanned documents get no OCR, and CAD files have no text extractor.

---

## Dependencies

- [[connectors]]: interfaces, gateway and prune contracts.
- [[connector-capability-checks]]: runs the named checks.
- [[permission-sync]]: schedules the doc sync and the group sync.

---

## Recipes

- `smb-local-test-server` **Run a file server and a domain for a test.**
  `backend/tests/external_dependency_unit/connectors/smb/README.md` starts a
  Samba Active Directory domain controller with a share, users, groups and a
  fixture tree, and gives the steps to connect a local Onyx to it.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/smb/` and
  `backend/tests/unit/ee/onyx/external_permissions/smb/`.
- Tests against a live Samba domain controller:
  `backend/tests/external_dependency_unit/connectors/smb/`.
- Only a person can check these on a real Windows Server, because Samba differs:
  the change time on a rename, the reparse point attribute of a junction, the
  offline attributes, and inherited entries on child access lists.
