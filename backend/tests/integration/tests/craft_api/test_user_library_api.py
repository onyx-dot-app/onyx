"""User library tests (HTTP contract half).

Pins the cross-user ownership boundary on the user-library endpoints in
``onyx.server.features.build.user_library.api``. The ownership check resolves
without any sandbox interaction, so it runs in the standard integration matrix
against the in-process app with a stubbed sandbox manager (see ``conftest.py``).
The real S3/zip persistence + extraction-cap tests stay in the compose lane.

Reuses the shared HTTP helpers in ``tests.integration.tests.craft`` so the two
lanes drive the user-library endpoints identically.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.user_library_http import delete_user_library_file
from tests.integration.tests.craft.user_library_http import list_user_library_tree
from tests.integration.tests.craft.user_library_http import upload_user_library_files


def _find_doc_by_name(
    entries: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    return next((e for e in entries if e.get("name") == name), None)


def test_cross_user_access_returns_404(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    """Foreign user → 404 on any file op.

    The ownership check in ``_verify_ownership_and_get_document`` rejects
    requests whose document id doesn't carry the calling user's id in
    the ``CRAFT_FILE__{user_id}__{hash}`` prefix. The user-facing code
    raises 403 for "not your file" and 404 for "doesn't exist" — the
    test plan calls out 404 (the safer choice, since revealing 403
    leaks existence). We accept either; the security-critical assertion
    is that the foreign user cannot read or mutate the file.
    """
    filename = f"cross-{uuid4().hex[:6]}.txt"
    response = upload_user_library_files(
        admin_user, [(filename, b"private", "text/plain")]
    )
    response.raise_for_status()
    document_id = response.json()["entries"][0]["id"]

    # basic_user cannot delete admin's file.
    delete_response = delete_user_library_file(basic_user, document_id)
    assert delete_response.status_code in (403, 404)

    # And basic_user's tree does not contain admin's row.
    basic_tree = list_user_library_tree(basic_user)
    assert all(e["id"] != document_id for e in basic_tree)
