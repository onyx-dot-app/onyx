# Descriptions of the sandbox tools that the model reads. A description names
# other tools by fields that SandboxTool.describe fills: `{shell}` (the
# shape's command tool), `{write_stdin}`, `{edit}`, `{create}`, `{list}`,
# `{materialize}` and `{replace}`.

from onyx.file_store.constants import ARTIFACT_TEXT_MAX_FILE_BYTES
from onyx.server.features.build.sandbox.harness_base import (
    AGENT_FILES_DIR,
    ARTIFACT_FILES_DIR,
    CHAT_FILES_DIR,
    ONYX_VM_FILES_ROOT,
    PROJECT_FILES_DIR,
)
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_TEXT_MAX_ITEMS,
    ARTIFACTS_MATERIALIZE_MAX_ITEMS,
    FIND_MAX_MATCHES,
    LIBRARY_SEARCH_MAX_QUERIES,
    MANAGE_LIBRARY_MAX_OPERATIONS,
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_FILES,
    READ_DEFAULT_LINES,
    READ_MAX_LINES,
)

# Where the chat's files are in the working directory
# (tools/tool_implementations/sandbox/file_copies.py).
CHAT_FILES_LAYOUT = (
    f"{CHAT_FILES_DIR}/ has copies of the chat's files: the user's uploads, "
    f"the project's files in {PROJECT_FILES_DIR}/ and the agent's files in "
    f"{AGENT_FILES_DIR}/. Each name starts with a short file ID. Onyx can "
    "put back the original files at any turn, so write a changed file to a "
    f"path outside {CHAT_FILES_DIR}/."
)

# The chat system prompt's section about the sandbox, when the turn offers
# sandbox tools: the VM facts that every tool shares, then `shell_line`:
# SANDBOX_SHELL_LINE when the turn offers the command tool, else empty.
SANDBOX_GUIDANCE = f"""
## Sandbox
You have a private Linux VM for this chat. Your working directory is {{workdir}}. Its files are saved and come back in later turns, except dependency and cache folders such as node_modules and .venv. The VM stops after a while without use; running commands, installed packages and files outside the working directory are then lost.
{CHAT_FILES_LAYOUT}{{shell_line}}
""".lstrip()
SANDBOX_SHELL_LINE = '\nDo not chain commands with `echo "===="` separators.'

# The command tool's description. `{start_rule}` is the shape's rule for
# another directory (EXEC_WORKDIR_RULE or EXEC_CD_RULE). The sandbox section
# gives the working directory's path, so tool definitions name no chat.
EXEC_COMMAND_DESCRIPTION = """Runs a command with bash, returning output or a session ID for ongoing interaction. Each call starts in your working directory; `cd` and environment changes do not carry over to the next call. {start_rule}

Usage:
- The command runs without a PTY: stdin, stdout and stderr are plain pipes.
- A command that is still running when the wait ends returns a session ID. It keeps running, also across turns, until it ends, reaches its time limit or the VM stops. Poll it with an empty {write_stdin} call and a long wait, or interrupt it.
- Output over the limit is cut in the middle. To read part of a long output, filter it with rg, head or tail."""
EXEC_WORKDIR_RULE = "Pass `workdir` when the command needs another directory."
EXEC_CD_RULE = "Start the command with `cd <dir> &&` when it needs another directory."
# A search result whose original file the chat's sandbox gets
# (tools/tool_implementations/sandbox/file_copies.py); the path is relative to
# the working directory, as the paths of chat files are.
SEARCH_FILE_GUIDANCE = (
    "Only a short excerpt from this document is shown below. The complete "
    'file is in the sandbox at "{filename}"; read or analyze it with shell '
    "commands. If the file is missing in the turn of this search, it may "
    "still be copying; try again shortly. In a later turn, search again to "
    "bring it back, or work from the excerpt.\n\n"
    "Excerpt: {content}"
)

# The end of an edit, write or apply_patch result that changed a chat file.
ATTACHMENTS_NOT_SAVED_NOTE = (
    f"Onyx can put back the original files in {CHAT_FILES_DIR}/ at any turn. "
    f"Write the changed file to a path outside {CHAT_FILES_DIR}/ to keep it."
)

WRITE_STDIN_DESCRIPTION = """Writes characters to the stdin of a command that {shell} started and returns recent output. Empty chars poll for new output; "\\u0003" interrupts the command.

Usage:
- Poll a running command with empty chars and a long wait.
- Interrupt commands that you no longer need with "\\u0003".
- A session ID stops working when its command ends or the VM stops."""

# Code mode keeps at most 2,000 characters of a tool description
# (code_mode/stubs.py MAX_TOOL_DESCRIPTION_CHARS); this one fits whole.
APPLY_PATCH_DESCRIPTION = """Edit files with a patch in this format, a stripped-down, file-oriented diff:

*** Begin Patch
[ one or more file sections ]
*** End Patch

Each file section starts with one of three headers:

*** Add File: <path> - create a new file. Every following line is a + line (the initial contents).
*** Delete File: <path> - remove an existing file. Nothing follows.
*** Update File: <path> - patch an existing file in place, optionally followed by *** Move to: <new path> to rename it.

An update has one or more hunks, each introduced by @@ (optionally followed by a header such as a class or function line). Within a hunk each line starts with " " (context), "-" (removed) or "+" (added).

Grammar:
Patch := Begin {{ FileOp }} End
Begin := "*** Begin Patch" NEWLINE
End := "*** End Patch" NEWLINE
FileOp := AddFile | DeleteFile | UpdateFile
AddFile := "*** Add File: " path NEWLINE {{ "+" line NEWLINE }}
DeleteFile := "*** Delete File: " path NEWLINE
UpdateFile := "*** Update File: " path NEWLINE [ "*** Move to: " newPath NEWLINE ] {{ Hunk }}
Hunk := "@@" [ header ] NEWLINE {{ (" " | "-" | "+") text NEWLINE }} [ "*** End of File" NEWLINE ]

Rules:
- Include a header with the intended action (Add/Delete/Update).
- Prefix new lines with + even when creating a file.
- Show 3 lines of context above and below each change. If that is not unique in the file, add @@ lines with the enclosing class or function.
- Paths are relative to the chat session directory, or absolute inside it. To change files elsewhere, use {shell}.
- The user sees the change as a diff. A successful call means the change is applied; a failed one returns an error.

Example:

*** Begin Patch
*** Add File: hello.txt
+Hello world
*** Update File: src/app.py
*** Move to: src/main.py
@@ def greet():
-    print("Hi")
+    print("Hello, world!")
     return None
*** Delete File: obsolete.txt
*** End Patch
"""

# The shape of Claude Code's Edit tool, which Claude models are trained on.
EDIT_DESCRIPTION = """Performs exact string replacements in files.

Usage:
- `old_string` must match the file exactly, including indentation. View the file with {shell} first, and copy the text without any line numbers.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.
- An empty `old_string` creates a new file with `new_string` as its contents. It fails when the file exists and is not empty.
- Paths are relative to the chat session directory, or absolute inside it. To change files elsewhere, use {shell}.
- The user sees the change as a diff. A successful call means the change is applied; a failed one returns an error.
"""

# The shape of Claude Code's Write tool.
WRITE_DESCRIPTION = """Writes a file, overwriting the existing file if there is one at the path.

Usage:
- Prefer {edit} for changes to an existing file: it sends only the changed text.
- Missing parent directories are created. An existing file keeps its permissions.
- Paths are relative to the chat session directory, or absolute inside it. To change files elsewhere, use {shell}.
- The user sees the change as a diff. A successful call means the change is applied; a failed one returns an error.
"""

LIBRARY_CREATE_LIBRARY_FILE_DESCRIPTION = f"""Publishes files from the VM for the user: this is how a file you made reaches the user. Each file shows as a download card in your reply.

Usage:
- Make and check files anywhere in the VM. Publish only finished deliverables, not drafts, scripts or intermediate files.
- `file` is one file, with an optional `title`; `files` is up to {PUBLISH_FILES_MAX_FILES} files instead. Each must be a regular file of at most {PUBLISH_FILES_MAX_BYTES >> 20} MiB, in the working directory or under {ONYX_VM_FILES_ROOT}. Copy a file from elsewhere into the working directory first.
- If one file fails, the call publishes none.
- Publishing the same path again adds a new version of that file; earlier cards keep their version. To add a version to a file of another chat, use {{replace}}.
- Do not paste the contents of a published file into your reply.
- Do not tell the user that a file is available unless this tool succeeded.
- Files published earlier, in this chat and in the user's other chats, can be found with {{list}} and copied into the VM with {{materialize}}.
"""

LIBRARY_LIST_DESCRIPTION = """Lists the files published in the user's chats, this chat included: the newest version of each file. By default, the files with the latest change (publish or rename) come first.

Usage:
- `sort` orders by first publish (created_at), latest change, a publish or rename (modified_at), file name or size; `sort_order` is asc or desc.
- `filters` keeps files by first publish, by latest change (publish or rename), by extension, or by category. `chat_id` lists the files of one chat. To find files by their content, name or title, search them instead.
- Each entry has the file's `library_file_id`, which stays the same across versions, and the `file_id` of its newest version, the path relative to its chat's working directory, and its chat. A version_number over 1 means that older versions exist.
- When more files exist, the result has a `next_cursor`. Send it with the same other arguments to get the next page.
"""

LIBRARY_SEARCH_DESCRIPTION = f"""Searches the user's published files, from all their chats, by content, name and title. Gives the best matches first, with snippets of the matching text.

Usage:
- `search_query` takes 1 to {LIBRARY_SEARCH_MAX_QUERIES} queries; a file that matches more of them ranks higher. A query matches the content by words and meaning, and also matches a file whose name, title or chat title has every word of the query. `search_title_only` matches only the names and titles.
- Only the newest version of each file is searched. A file or version published in the last minute may not be searchable by content yet; it still matches by name and title, and its result has `content_indexed` false. Its content matches and snippets can then come from its previous version.
- `filters` keeps files by first publish, by latest change (publish or rename), by extension or by category. `chat_id` keeps the files of one chat. `scope.file_refs` searches only the files it names.
- With `sort` relevance (the default), content matches by meaning too, so the last results can be only loosely related. The other sorts match content by its words only and order the best matches: by first publish (created_at), latest change, a publish or rename (modified_at), name or size.
- A snippet has no line number. To find it in the file, find a phrase from the snippet in that file. `result_format` "metadata_only" leaves out the snippets.
- When more results exist, the result has a `next_cursor`. Send it with the same other arguments to get the next page.
- When the result has `content_search` "unavailable", this deployment matches names and titles only.
"""

LIBRARY_PREPARE_MATERIALIZE_DESCRIPTION = f"""Copies published files from the user's chats into this chat's working directory. The call ends when the copies are done, and gives each item's path and status.

Usage:
- Each item takes a `file_id` (that version) or a `library_file_id` (its newest version), from {{list}} or a {{create}} result.
- By default, a copy goes to {ARTIFACT_FILES_DIR}/<short file ID>-<name>, and a second copy of the same file uses the one that is there. `destination.directory`, an item's `relative_directory` and `file_name` choose another place and name in the working directory, outside {CHAT_FILES_DIR}/ or in {ARTIFACT_FILES_DIR}/.
- `destination.conflict_policy` applies to every copy except one to the default {ARTIFACT_FILES_DIR}/<short file ID>-<name>. It decides what happens when a file is already there: dedupe (the default) adds " (N)" to the name, overwrite replaces it, error fails the item. Under every policy, a copy to the default {ARTIFACT_FILES_DIR}/<short file ID>-<name> uses the file that is there when its size matches, and writes it again otherwise.
- One call copies at most {ARTIFACTS_MATERIALIZE_MAX_ITEMS} files. A failed item does not stop the others.
- The chat does not keep files in {CHAT_FILES_DIR}/: a sandbox restart removes them. To change a file, copy it to a directory outside {CHAT_FILES_DIR}/, change it there, and add it as a new version with {{replace}}.
"""

LIBRARY_REPLACE_LIBRARY_FILE_DESCRIPTION = f"""Adds a version to a published file of the user's chats, this chat included, from a file in the VM. The file keeps its name, type and place in its chat; earlier versions and their cards stay.

Usage:
- `library_file_id` is from {{list}} or a {{create}} result. `file` is the new content, at most {PUBLISH_FILES_MAX_BYTES >> 20} MiB, in the working directory or under {ONYX_VM_FILES_ROOT}, with the published file's extension. For a file of another type, publish a new file instead.
- Pass the version_number that you last read as `expected_current_version`. If the file has a newer version, the call fails and changes nothing: copy the newest version with {{materialize}}, merge your change, and replace again.
- The user sees a download card for the new version. `title` defaults to the current version's title. `version_reason` is a short note on why the version exists.
"""

LIBRARY_MANAGE_LIBRARY_DESCRIPTION = f"""Renames and deletes published files of the user's chats, this chat included, restores older versions, and adds stored files as new versions.

Usage:
- `operations` runs up to {MANAGE_LIBRARY_MAX_OPERATIONS} operations in order. Each gives one result; a failed operation does not stop the others.
- rename: `{{{{"operation": "rename", "target": {{{{"library_file_id": ...}}}}, "new_name": "summary.md"}}}}`. `target` takes a `library_file_id` or the `file_id` of any version. The new name is a file name, not a path, with the current extension. Every version and later publishes of the same path keep it.
- restore_version: `{{{{"operation": "restore_version", "library_file_id": ..., "version_number": 2}}}}` adds a copy of that version as the newest version, with its title. Earlier versions stay.
- update: `{{{{"operation": "update", "library_file_id": ..., "file_uri": {{{{"file_id": ...}}}}}}}}` adds a copy of a version of any published file of the user, of the same type, as the file's newest version. `file_id` takes a file ID or a url. `file_name` renames the file, with the same extension.
- delete: `{{{{"operation": "delete", "target": {{{{"library_file_id": ...}}}}}}}}` deletes the file with all its versions; its download cards stop working. `target` takes a `library_file_id` or the `file_id` of any version; a `version_number` must be the newest.
- Deleting asks the user, and the whole call waits for the answer. Put deletes in their own call.
"""

_TEXT_SCOPE = f"""- The text is extracted on the server, without starting the VM: PDF pages, slides and spreadsheet sheets (one page per sheet), Word, HTML, text and other document formats. Images have no text. A file larger than {ARTIFACT_TEXT_MAX_FILE_BYTES >> 20} MiB is not read here; copy it into the VM instead.
- One call takes up to {ARTIFACT_TEXT_MAX_ITEMS} files. If any file is refused, the call fails with every reason."""

LIBRARY_READ_DESCRIPTION = f"""Reads the text of published files from the user's chats, this chat included, by numbered lines or by pages.

Usage:
- Each item takes a `file_id` (that version) or a `library_file_id` (its newest version, or `version_number`). Each result gives the version read and the file's latest_version_number.
- mode lines (the default) reads `max_lines` lines ({READ_DEFAULT_LINES} by default, at most {READ_MAX_LINES}) from `start_line`. mode pages reads pages `start_page` to `end_page` of a PDF, slide deck or spreadsheet. Page breaks show as `--- page N ---` lines.
- A long result stops early: read again with `start_line` set to its `next_start_line`. In mode pages, keep the same pages; the read goes on to their end, and `next_start_line` is null once their last line shows. A very long line is cut.
{_TEXT_SCOPE}
"""

LIBRARY_FIND_DESCRIPTION = f"""Finds the lines that contain a text or a regular expression in published files from the user's chats, this chat included, like grep. Each match gives its line number and page; read the file from that line for more.

Usage:
- Each item takes a `file_id` (that version) or a `library_file_id` (its newest version, or `version_number`), and a `pattern`.
- The pattern is literal text by default, in any case; `regex` makes it a regular expression and `case_sensitive` matches case. A pattern matches within one line.
- `start_line`/`end_line` or `start_page`/`end_page` limit the search. `context_before_lines` and `context_after_lines` show nearby lines.
- At most `max_matches` matches come back (at most {FIND_MAX_MATCHES}); `next_match_offset` gives the next ones as `match_offset`, with the same `start_line`. A search that takes too long stops with timed_out and `reached_line`, and it can stop after matches that did not fit: page through them with `next_match_offset` first. When `next_match_offset` is null, search the rest with `start_line` set to `reached_line` and `match_offset` 0.
{_TEXT_SCOPE}
"""

# The artifact tool (sandbox_tools.ArtifactTool). The code mode program search
# matches its first sentence.
ARTIFACT_DESCRIPTION = f"""Publish, replace, list, search, read, find in, rename, restore and delete the user's published files (artifacts). A published file shows as a download card in your reply, and its url opens it for the user.

Actions:
- publish (the default): gives `file_path`, or up to {PUBLISH_FILES_MAX_FILES} `file_paths`, from the VM to the user; all are published, or none. Each file is at most {PUBLISH_FILES_MAX_BYTES >> 20} MiB, in the working directory or under {ONYX_VM_FILES_ROOT}. Publishing the same path again adds a new version. Publish only finished deliverables, and do not paste their contents into your reply.
- publish with `url` and `file_path`: adds a version to that published file, also one of another chat; it keeps its name and type, so `file_path` needs its extension. Use the url from your last result: if the file has a newer version than the url names, the call fails and changes nothing. `force` adds the version anyway; older versions stay. `label` is a short note on why the version exists.
- publish with `url` and `path`: adds a copy of the published file that `path` names (a file ID or a url), of the same type, as the url's newest version, with the same version rule.
- list: the user's published files from all their chats, newest first. `type` keeps one type (image, sheet, slides, report, other); `after` takes the `next_cursor` of the previous page. With `query`, list searches the content, names and titles of the files and gives the best matches first, with snippets of the matching text. A result with `content_indexed` false is not searchable by content yet, usually for a minute after its publish: it matches by name and title, and its content matches and snippets can come from its previous version.
- read: shows the text of published files as numbered lines, without starting the VM. Name them with `url` (a url from an earlier result; one that ends in /v<N> names that version), or with `path` or `paths`, each a url or a file ID, up to {ARTIFACT_TEXT_MAX_ITEMS} files. `offset` is the first line and `limit` the most lines ({READ_DEFAULT_LINES} by default); a long result gives `next_start_line`. `offset` takes one file: page one file at a time. Images and files over {ARTIFACT_TEXT_MAX_FILE_BYTES >> 20} MiB have no text here.
- read with `query`: finds the lines that contain the text, in any case, with their line and page numbers; `limit` caps the matches and `offset` skips matches (`next_match_offset`).
- read with `out_dir`: copies up to {ARTIFACTS_MATERIALIZE_MAX_ITEMS} published files into `out_dir`, in the working directory, outside {CHAT_FILES_DIR}/ or in {ARTIFACT_FILES_DIR}/, to work with them in the VM. To change a file, read it into a directory outside {CHAT_FILES_DIR}/, change it there, and publish it with its url.
- rename: gives the file at `url` the file name `name`, not a path, with the current extension. Every version and later publishes keep it.
- restore: adds a copy of the version at `url`, which ends in /v<N>, as the newest version. Earlier versions stay.
- delete: deletes the file at `url` (the url of its newest version, or one without /v<N>) with all its versions, after the user approves; its download cards stop working.
- A url is a link the user can open; give it to the user to point at a file.
"""
ARTIFACT_RESULTS = (
    "publish: {files: [{library_file_id, file_id, version_number, file_name, "
    "title, path, url}]}. list: {files: [{library_file_id, file_id, "
    "version_number, file_name, title, artifact_type, mime_type, "
    "file_size_bytes, created_at, modified_at, chat_id, chat_title, path, url}], "
    "next_cursor}. list with query: {results: [{file: {the list entry keys}, "
    "score, content_indexed, snippets}], next_cursor, complete}. read: "
    "{items: [{file: {...the list entry, "
    "latest_version_number}, total_lines, total_pages, start_line, end_line, "
    "text, next_start_line, truncated}]}. read with query: {items: [{file, "
    "total_matches_seen, matches: [{line, page, text, before, after}], "
    "next_match_offset, timed_out, reached_line, truncated}]}. read with "
    "out_dir: {items: [{library_file_id, file_id, version_number, file_name, "
    "path, file_size_bytes, mime_type, url, status, error}]}. rename, restore "
    "and publish with path: {results: [{operation, ok, library_file_id, "
    "file_id, version_number, file_name, url, version_reason}]}. delete: "
    "{results: [{operation, ok, library_file_id, file_name, deleted_versions}]}."
)
