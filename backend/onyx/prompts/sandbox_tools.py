# Descriptions of the sandbox tools that the model reads.

from onyx.server.features.build.sandbox.harness_base import (
    AGENT_FILES_DIR,
    ARTIFACT_FILES_DIR,
    CHAT_FILES_DIR,
    ONYX_VM_FILES_ROOT,
    PROJECT_FILES_DIR,
)
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACTS_MATERIALIZE_MAX_ITEMS,
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_FILES,
)

# The chat system prompt's section about the sandbox, when the turn offers the
# sandbox tools; `uses` names each tool with its use (the *_USE texts).
SANDBOX_GUIDANCE = """
## Sandbox
You have a private Linux VM for this chat. Its files persist across turns in your working directory, the chat's session directory. {uses}
""".lstrip()
# In code mode the tools are functions of `execute_code` programs.
SANDBOX_CODE_MODE_NOTE = " Call them from `execute_code` programs."
EXEC_COMMAND_USE = "run commands with {name}"
WRITE_STDIN_USE = "use {name} for commands that are still running"
APPLY_PATCH_USE = "edit files with {name}"
EDIT_USE = "edit files with {name}"
WRITE_USE = "create or overwrite files with {name}"

EXEC_COMMAND_DESCRIPTION = (
    "Runs a command with bash, returning output or a session ID for ongoing "
    "interaction. The command runs without a PTY: stdin, stdout and stderr are "
    "plain pipes. The default working directory is this chat's session directory."
)
# The end of the exec_command description in a chat with chat files
# (tools/tool_implementations/sandbox/file_copies.py).
CHAT_FILES_LAYOUT = (
    f"{CHAT_FILES_DIR}/ has copies of the chat's files: the user's uploads, "
    f"the project's files in {PROJECT_FILES_DIR}/ and the agent's files in "
    f"{AGENT_FILES_DIR}/. Each name starts with a short file ID. Onyx can "
    "put back the original files at any turn, so write a changed file to a "
    f"path outside {CHAT_FILES_DIR}/."
)

# A search result whose original file the chat's sandbox gets
# (tools/tool_implementations/sandbox/file_copies.py); the path is relative to
# the working directory, as the paths of chat files are.
SEARCH_FILE_GUIDANCE = (
    "Only a short excerpt from this document is shown below. The complete "
    'file is in the sandbox at "{filename}"; read or analyze it with '
    "exec_command. If the file is missing in the turn of this search, it may "
    "still be copying; try again shortly. In a later turn, search again to "
    "bring it back, or work from the excerpt.\n\n"
    "Excerpt: {content}"
)

# The end of an edit, write or apply_patch result that changed a chat file.
ATTACHMENTS_NOT_SAVED_NOTE = (
    f"Onyx can put back the original files in {CHAT_FILES_DIR}/ at any turn. "
    f"Write the changed file to a path outside {CHAT_FILES_DIR}/ to keep it."
)

WRITE_STDIN_DESCRIPTION = (
    "Writes characters to the stdin of a command that exec_command started and "
    "returns recent output. Empty chars poll for new output; "
    '"\\u0003" interrupts the command.'
)

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
Patch := Begin { FileOp } End
Begin := "*** Begin Patch" NEWLINE
End := "*** End Patch" NEWLINE
FileOp := AddFile | DeleteFile | UpdateFile
AddFile := "*** Add File: " path NEWLINE { "+" line NEWLINE }
DeleteFile := "*** Delete File: " path NEWLINE
UpdateFile := "*** Update File: " path NEWLINE [ "*** Move to: " newPath NEWLINE ] { Hunk }
Hunk := "@@" [ header ] NEWLINE { (" " | "-" | "+") text NEWLINE } [ "*** End of File" NEWLINE ]

Rules:
- Include a header with the intended action (Add/Delete/Update).
- Prefix new lines with + even when creating a file.
- Show 3 lines of context above and below each change. If that is not unique in the file, add @@ lines with the enclosing class or function.
- Paths are relative to the chat session directory, or absolute inside it. To change files elsewhere, use exec_command.

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
- `old_string` must match the file exactly, including indentation. View the file with exec_command first, and copy the text without any line numbers.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.
- An empty `old_string` creates a new file with `new_string` as its contents. It fails when the file exists and is not empty.
- Paths are relative to the chat session directory, or absolute inside it. To change files elsewhere, use exec_command.
"""

# The shape of Claude Code's Write tool.
WRITE_DESCRIPTION = """Writes a file, overwriting the existing file if there is one at the path.

Usage:
- Prefer edit for changes to an existing file: it sends only the changed text.
- Missing parent directories are created. An existing file keeps its permissions.
- Paths are relative to the chat session directory, or absolute inside it. To change files elsewhere, use exec_command.
"""

PUBLISH_FILES_DESCRIPTION = f"""Gives files from the VM to the user. Each file shows as a download card in your reply.

Usage:
- Make and check files anywhere in the VM. Publish only finished deliverables, not drafts, scripts or intermediate files.
- Each path must be a regular file of at most {PUBLISH_FILES_MAX_BYTES >> 20} MiB, in the working directory or under {ONYX_VM_FILES_ROOT}. Copy a file from elsewhere into the working directory first.
- One call publishes at most {PUBLISH_FILES_MAX_FILES} files. If one file fails, the call publishes none.
- Publishing the same path again adds a new version of that file; earlier cards keep their version.
- Do not paste the contents of a published file into your reply.
- Do not tell the user that a file is available unless this tool succeeded.
- Files published earlier, in this chat and in the user's other chats, can be found and copied into the VM with the library tools.
"""

LIBRARY_LIST_DESCRIPTION = """Lists the files that were published with publish_files in the user's chats, this chat included: the newest version of each file. By default, the most recently published come first.

Usage:
- `sort` orders by first publish (created_at), latest publish (modified_at), file name or size; `sort_order` is asc or desc.
- `filters` keeps files by publish time, by extension, or by category. `chat_id` lists the files of one chat. `query` finds text in the file name, the file's title or the chat's title, in any case.
- Each entry has the file's `library_file_id`, which stays the same across versions, and the `file_id` of its newest version, the path relative to its chat's working directory, and its chat. A version_number over 1 means that older versions exist.
- When more files exist, the result has a `next_cursor`. Send it with the same other arguments to get the next page.
"""

LIBRARY_PREPARE_MATERIALIZE_DESCRIPTION = f"""Copies published files from the user's chats into this chat's working directory. The call ends when the copies are done, and gives each item's path and status.

Usage:
- Each item takes a `file_id` (that version), from library_list or a publish_files result, or a `library_file_id` (its newest version), from library_list.
- By default, a copy goes to {ARTIFACT_FILES_DIR}/<short file ID>-<name>, and a second copy of the same file uses the one that is there. `destination.directory`, an item's `relative_directory` and `file_name` choose another place and name in the working directory, outside {CHAT_FILES_DIR}/ or in {ARTIFACT_FILES_DIR}/.
- `destination.conflict_policy` applies to every copy except one to the default {ARTIFACT_FILES_DIR}/<short file ID>-<name>. It decides what happens when a file is already there: dedupe (the default) adds " (N)" to the name, overwrite replaces it, error fails the item. Under every policy, a copy to the default {ARTIFACT_FILES_DIR}/<short file ID>-<name> uses the file that is there when its size matches, and writes it again otherwise.
- One call copies at most {ARTIFACTS_MATERIALIZE_MAX_ITEMS} files. A failed item does not stop the others.
- The chat does not keep files in {CHAT_FILES_DIR}/: a sandbox restart removes them. To change a file, copy it to a directory outside {CHAT_FILES_DIR}/, change it there, and publish it from that path.
"""
