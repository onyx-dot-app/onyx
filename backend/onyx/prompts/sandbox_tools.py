# Descriptions of the sandbox tools that the model reads.

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
