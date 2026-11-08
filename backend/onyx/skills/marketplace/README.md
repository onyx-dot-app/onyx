# Marketplace archive processing

This package provides internal sync building blocks. It does not change the
one-time GitHub import or expose a marketplace API.

## Resource limits

Repository input keeps the 25 MiB compressed limit and 10,000 entry limit.
Each skill separately keeps the default upload limits: 25 MiB ZIP, 500 files,
25 MiB per file, and 100 MiB unpacked.

The archive reader also has independent processing safeguards:

- A gzip stream may expand to at most 1 GiB, including tar headers, padding,
  and unrelated files. The reader inflates it once into a temporary spool.
  Only the first 1 MiB stays in memory; larger spools use temporary disk.
- Member reads share a 1 GiB byte budget, for both ZIP and tar. The budget
  counts actual returned bytes, including repeated reads and manifests.
  ZIP members outside the selected marketplace need no inflation. All supported
  stream reads, including readinto, lines and iteration, use that budget.
- One tar extension header and each JSON manifest may use at most 1 MiB.
  Member data reads use the shared member budget after metadata parsing finishes.
- Paths have at most 64 segments and 4,096 UTF-8 bytes. The stored path and
  parent-prefix index shares a 25 MiB ceiling with retained TAR PAX metadata.
  Each member charges its metadata dictionary size and UTF-8 keys and values.
  Global headers count for every copy, including GitHub commit headers.
  Path limits apply before unbounded prefix allocation.

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
