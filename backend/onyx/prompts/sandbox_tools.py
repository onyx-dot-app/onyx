# Descriptions of the sandbox tools that the model reads.

EXEC_COMMAND_DESCRIPTION = (
    "Runs a command with bash in a private Linux sandbox, returning output or a "
    "session ID for ongoing interaction. The command runs without a PTY: stdin, "
    "stdout and stderr are plain pipes. The default working directory is this "
    "chat's session directory; files there persist across turns of the chat. "
    "Use apply_patch for manual file edits."
)

WRITE_STDIN_DESCRIPTION = (
    "Writes characters to the stdin of a command that exec_command started and "
    "returns recent output. Empty chars poll for new output; "
    '"\\u0003" interrupts the command.'
)

# Code mode keeps at most 2,000 characters of a tool description
# (code_mode/stubs.py MAX_TOOL_DESCRIPTION_CHARS); this one fits whole.
APPLY_PATCH_DESCRIPTION = """Use the `apply_patch` tool to edit files. The patch format is a stripped-down, file-oriented diff:

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
