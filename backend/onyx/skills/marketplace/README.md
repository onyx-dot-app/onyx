# Marketplace archive processing

This package provides sync and preview building blocks. The marketplace API uses
its provider adapter and reader.

## Webhook setup transport

The GitHub adapter resolves an exact branch or tag for registration. `HEAD` uses
the default branch at setup time; run setup again after that branch changes.
Pinned commits and ambiguous branch/tag names cannot
register. Explicit `refs/heads/` or `refs/tags/` names resolve ambiguity.
Registration lists hooks by the exact callback URL and updates an existing hook.
This also recovers a lost creation response. Hooks use signed JSON with certificate
verification. GitHub errors use controlled messages; credentials and provider
response bodies are not returned. API setup must save signing state before calling
GitHub, then recheck authority and source identity before saving the hook ID.
Only a saved hook ID enables push syncs or delivery timestamps. Signed pings can arrive before that save,
including from a replacement hook. Only pings matching the saved hook ID update
the verified delivery time. A failed initial setup cannot queue push syncs.
`POST /marketplaces/{id}/webhook` performs this sequence on self-hosted installs.
Setup errors leave Sync now available. The API reuses signing intent on retries;
it exposes registration and delivery status without the secret. UI controls follow
in a separate layer.

## Resource limits

Repository input keeps the 25 MiB compressed limit and 10,000 entry limit.
Each skill separately keeps the default upload limits: 25 MiB ZIP, 500 files,
25 MiB per file, and 100 MiB unpacked.

The archive reader also has independent processing safeguards:

- ZIP directory metadata reads are capped at 1 MiB before parsing. Larger
  directories fail even within the entry limit. Only stored and deflated ZIP
  members are supported; other compression methods fail before member reads.
- A gzip stream may expand to at most 1 GiB, including tar headers, padding,
  and unrelated files. The reader inflates it once into a temporary spool.
  Only the first 1 MiB stays in memory; larger spools use temporary disk.
- Member reads share a 1 GiB byte budget, for both ZIP and tar. The budget
  counts actual returned bytes, including repeated reads and manifests.
  ZIP members outside the selected marketplace need no inflation. All supported
  stream reads, including readinto, lines and iteration, use that budget.
- `read`, `readline` and `readlines` return at most 4 MiB. An unsized read, a larger sized read,
  one line, or `readlines` fails if its result would be longer. It does
  not truncate the result. Callers must read larger members in chunks.
  `read1` may return less, and `readinto` fills larger buffers in steps.
- TAR metadata reads share a 16 MiB budget during enumeration, including chained
  extension headers and sparse maps. The headers before one member may use at
  most 32 KiB. This limits chained headers and parser recursion before
  allocation. Each JSON manifest may use at most 1 MiB.
  Member data reads use the shared member budget after metadata parsing finishes.
- Sparse TAR members fail the read after their bounded headers parse. `git
  archive` does not write them. Global PAX comments, long paths and long link
  targets stay supported when their headers fit in 32 KiB.
- Paths have at most 64 segments and 4,096 UTF-8 bytes. The stored path and
  parent-prefix index shares a 25 MiB ceiling with retained TAR PAX metadata.
  Each member charges its metadata dictionary size and the Python object size
  of each key and value. This is a conservative estimate, not exact memory use.
  Global headers count for every copy, including GitHub commit headers.
  Path limits apply before unbounded prefix allocation.
- Unique JSON manifests share a 25 MiB budget, including the marketplace manifest.
  Each archive path is parsed once per read. Shared plugin roots reuse parsed configs.
  The cache retains discovery fields and component presence, not unrelated metadata.
- A read accepts at most 500 plugin entries and 500 declared paths across
  all entries and plugin manifests, including `skills`, `agents`, and `commands`.
  Plugin counts are checked before discovery. Each explicit path list consumes
  the shared budget before it is scanned or expanded. Repeated paths count again.

The 1 GiB ceiling permits ten full 100 MiB skills plus tar overhead.
It bounds temporary disk and decompression work for highly compressed inputs.
It is not the former 100 MiB repository-wide skill limit. Repositories can
contain more than 100 MiB of valid skill content.

These safeguards can reject an otherwise valid repository within the compressed
and entry limits. In particular, a tar archive with large unrelated files can
fail while a ZIP with those unread files succeeds. Processing failures must
fail the whole read. A sync must retain the last good state and retire nothing.
A future streaming staging API can support larger repositories without retaining
all output bundles in memory. Raising these limits requires resource measurements.

No archive path is extracted to the filesystem. Absolute paths, traversal,
duplicate paths, and file/directory conflicts fail the read. Special members
remain visible as unreadable entries, so callers can reject affected content
without opening links or devices. Colons in relative filenames are accepted;
Windows drive paths are refused. A single leading `./` is accepted.

## Complete marketplace reads

`read_marketplace_archive` selects the Claude manifest before the Codex manifest,
at the requested folder only. A missing or invalid manifest fails the read.
A blocked skill keeps its plugin/name key. Reconciliation must retain its current
version. Failed reads return no entries and must never cause retirement.

Explicit entry `skills` paths replace default discovery. Each path can name a
skill folder or a container of direct child skill folders. This deliberately
differs from Claude's additive default. Invalid skills remain blocked entries.
Mixed-component and remote plugins remain unsupported entries.

The default `skills/` path remains a container when all child definitions are
missing. Its declared and implicit forms preserve the same child keys.
Other declared paths become containers when a direct child has `SKILL.md`.
Otherwise they retain their own key, even when their definition is missing.
Plugin manifest `skills` paths also load. Claude paths add to default discovery;
Codex compatibility paths replace it. Entry paths suppress defaults but retain
manifest paths. When both compatibility manifests exist, Claude takes precedence.
Overlapping discovery sources load each path once; different paths with the same
key fail the read. A nested plugin can load its root `SKILL.md` when neither a
`skills` key nor a default skills directory with members exists.
If that root definition disappears while other plugin files remain, its entry
stays blocked with the same key. Sync preserves the existing Skill.

Tar reads require two zero end blocks and only zero padding afterward. A valid gzip wrapper
does not prove that its tar body is complete. Missing or damaged tar headers
fail the read before reconciliation can infer removed skills.

Each skill path builds once per read, even when many plugins reference it.
Unique generated bundles share a 256 MiB ceiling. This permits ten maximum-size
25 MiB ZIPs while bounding retained output. Nested skill paths count separately,
because their bundles differ. Exceeding this ceiling fails the whole read.
One in-progress bundle also consumes bounded memory under the per-skill limits.
This ceiling can reject otherwise valid large catalogs. It is separate from
unpacked skill limits and includes no duplicate charge for a shared path.

Markdown definitions in plugin `agents/` and `commands/` are components;
`agents/openai.yaml` metadata alone is not. Claude's bin, output-styles, monitors,
workflows, settings, and experimental monitors/themes also prevent skill import.
An unreadable manifest or plugin config fails the read. An unreadable skill
member blocks that skill. Unrelated special members do not affect the result.

The reader accepts leading `./` archive entries and Claude `metadata.pluginRoot`
for bare source names. It identifies Codex root `plugin.json` as an unsupported
format rather than assuming legacy manifest semantics. Root `mcp.json` prevents
partial skill import. Full Agent Plugins schema support needs separate work.

References: [Claude manifest](https://code.claude.com/docs/en/plugins-reference),
[Claude marketplace](https://code.claude.com/docs/en/plugins/marketplace-reference),
[Codex metadata](https://learn.chatgpt.com/docs/build-skills), and
[Codex Agent Plugins parser](https://github.com/openai/codex/blob/main/codex-rs/core-plugins/src/agent_plugin_manifest.rs).
