"""Chat turns that carry a file attachment.

Each user uploads one file up front, then attaches it to every message. This
exercises the chat-setup path that loads attached files from object storage
(MinIO/S3) inside `build_chat_turn` *while the DB connection is held* — the
suspected connection-pool-hold contributor that plain-text scenarios never
touch (they attach no files). Set ONYX_SESSION_TURNS > 1 to also accumulate
files across a growing history (a file-heavy long chat).

Tuning (env):
    ONYX_FILE_KB   uploaded file size in KB (default 512) — bigger = longer
                   object-storage read held across the connection.

Selected explicitly (not in the default mix):
    locust -f locustfile.py FileAttachmentUser
"""

from __future__ import annotations

import uuid

from onyx_client.chat_user import OnyxChatUser
from onyx_client.env import env_int


class FileAttachmentUser(OnyxChatUser):
    abstract = False

    scenario_prefix: str = "fileattach"

    def setup_files(self) -> None:
        kb = env_int("ONYX_FILE_KB", 512)
        # ~1KB repeating unit, truncated to the requested size.
        unit = b"Onyx load-test attachment payload. Lorem ipsum dolor sit. " * 18
        blob = (unit * max(1, kb))[: kb * 1024]
        filename = f"loadtest-{uuid.uuid4().hex[:8]}.txt"

        with self.client.post(
            "/api/user/projects/file/upload",
            files={"files": (filename, blob, "text/plain")},
            name=f"{self.scenario_prefix}:upload",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}: {response.text[:200]}")
                return
            user_files = response.json().get("user_files", [])
            if not user_files:
                response.failure("upload: no user_files in response")
                return
            response.success()
            self.file_descriptors = [
                {
                    "id": uf["file_id"],
                    "type": uf["chat_file_type"],
                    "name": uf["name"],
                    "user_file_id": str(uf["id"]),
                }
                for uf in user_files
            ]

    # chat_turn (the @task) is inherited from OnyxChatUser; it now includes
    # self.file_descriptors in the payload, so every turn attaches the file.
