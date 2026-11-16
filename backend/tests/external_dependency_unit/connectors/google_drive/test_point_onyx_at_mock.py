"""The test-side patches that point Onyx at the mock Drive server, in a test
block and for a whole process (sitecustomize.py)."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive import source_operations
from onyx.connectors.google_utils import google_auth
from onyx.connectors.google_utils.shared_constants import GOOGLE_TOKEN_URI
from tests.integration.mock_services.mock_google_drive_server.mock_gdrive.patch_onyx import (
    point_onyx_at_mock,
)

_MOCK_URL = "http://127.0.0.1:9650"
_MOCK_DIR = (
    Path(__file__).resolve().parents[4]
    / "tests"
    / "integration"
    / "mock_services"
    / "mock_google_drive_server"
)


def test_valid_oauth_creds_refresh_at_the_mock() -> None:
    """A valid token is returned without a refresh. The client refreshes it
    later, so it must already point at the mock's token endpoint."""
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    token_json = json.dumps(
        {
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "token": "access",
            "expiry": expiry.isoformat() + "Z",
        }
    )

    with point_onyx_at_mock(_MOCK_URL):
        creds = google_auth.get_google_oauth_creds(
            token_json_str=token_json, source=DocumentSource.GOOGLE_DRIVE
        )
    assert creds is not None
    assert creds.valid
    assert creds.token_uri == f"{_MOCK_URL}/token"

    after = google_auth.get_google_oauth_creds(
        token_json_str=token_json, source=DocumentSource.GOOGLE_DRIVE
    )
    assert after is not None
    assert after.token_uri == GOOGLE_TOKEN_URI


def test_the_patches_end_with_the_block() -> None:
    docs_url = source_operations._DOCS_API_DOCUMENT_URL
    with point_onyx_at_mock(_MOCK_URL):
        assert google_auth.GOOGLE_TOKEN_URI == f"{_MOCK_URL}/token"
        assert source_operations._DOCS_API_DOCUMENT_URL.startswith(f"{_MOCK_URL}/")
        assert source_operations._FORMS_API_FORM_URL.startswith(f"{_MOCK_URL}/")
    assert google_auth.GOOGLE_TOKEN_URI == GOOGLE_TOKEN_URI
    assert source_operations._DOCS_API_DOCUMENT_URL == docs_url


def test_sitecustomize_patches_a_new_process() -> None:
    """With the mock folder on PYTHONPATH and MOCK_GDRIVE_URL set, Onyx's
    modules are patched when they are imported."""
    script = (
        "import json\n"
        "from googleapiclient.discovery import build\n"
        "from onyx.connectors.google_drive import source_operations\n"
        "from onyx.connectors.google_utils import google_auth\n"
        "client = build('drive', 'v3', developerKey='unused')\n"
        "print(json.dumps({\n"
        "    'token': google_auth.GOOGLE_TOKEN_URI,\n"
        "    'docs': source_operations._DOCS_API_DOCUMENT_URL,\n"
        "    'client': client._baseUrl,\n"
        "}))\n"
    )
    backend_dir = _MOCK_DIR.parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_MOCK_DIR), str(backend_dir)])
    env["MOCK_GDRIVE_URL"] = _MOCK_URL
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )

    seen = json.loads(result.stdout.strip().splitlines()[-1])
    assert seen["token"] == f"{_MOCK_URL}/token"
    assert seen["docs"] == f"{_MOCK_URL}/v1/documents/{{doc_id}}"
    assert seen["client"] == f"{_MOCK_URL}/drive/v3/"
