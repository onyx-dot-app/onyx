UNSUPPORTED_FILE_TYPE_CONTENT = ""  # keep empty for now
DRIVE_FOLDER_TYPE = "application/vnd.google-apps.folder"
DRIVE_SHORTCUT_TYPE = "application/vnd.google-apps.shortcut"
DRIVE_FILE_TYPE = "application/vnd.google-apps.file"

# File ids kept to yield or count a file shared on several paths once. Ids
# measure ~119 bytes each, so this holds the checkpoint's set near 95 MB, under
# CHECKPOINT_SIZE_LIMIT_BYTES. Past the cap duplicates go through again.
MAX_DEDUP_DRIVE_FILE_IDS = 800_000

# Files shared by link after 2021 need their resource key on every request.
DRIVE_RESOURCE_KEY_HEADER = "X-Goog-Drive-Resource-Keys"
DRIVE_RESOURCE_KEY_FIELD = "resourceKey"
