"""The test-side patches that point Onyx at the mock Drive server, in a test
block and for a whole process (sitecustomize.py)."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive import source_operations
from onyx.connectors.google_utils import google_auth
from onyx.connectors.google_utils.shared_constants import GOOGLE_TOKEN_URI
from tests.integration.mock_services.mock_google_drive_server.mock_gdrive.patch_onyx import (
    point_onyx_at_mock,
)

_MOCK_URL = "http://127.0.0.1:9650"
_OTHER_MOCK_URL = "http://127.0.0.1:9651"
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


def test_the_inner_block_selects_the_url() -> None:
    """A nested block sends clients to its own URL, and the outer URL comes
    back when the nested block ends."""
    with point_onyx_at_mock(_MOCK_URL):
        with point_onyx_at_mock(_OTHER_MOCK_URL):
            inner = build("drive", "v3", developerKey="unused")
        outer = build("drive", "v3", developerKey="unused")
    assert inner._baseUrl == f"{_OTHER_MOCK_URL}/drive/v3/"
    assert outer._baseUrl == f"{_MOCK_URL}/drive/v3/"


def _run_with_sitecustomize(script: str) -> dict[str, str]:
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
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_spec_probe_keeps_the_pending_patch() -> None:
    """A find_spec probe before the import does not use up the patch."""
    script = (
        "import importlib.util, json\n"
        "assert importlib.util.find_spec('googleapiclient.discovery')\n"
        "from googleapiclient.discovery import build\n"
        "client = build('drive', 'v3', developerKey='unused')\n"
        "print(json.dumps({'client': client._baseUrl}))\n"
    )
    seen = _run_with_sitecustomize(script)
    assert seen["client"] == f"{_MOCK_URL}/drive/v3/"


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
    seen = _run_with_sitecustomize(script)
    assert seen["token"] == f"{_MOCK_URL}/token"
    assert seen["docs"] == f"{_MOCK_URL}/v1/documents/{{doc_id}}"
    assert seen["client"] == f"{_MOCK_URL}/drive/v3/"
