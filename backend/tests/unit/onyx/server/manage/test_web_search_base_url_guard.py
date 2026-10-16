from __future__ import annotations

from unittest.mock import MagicMock

from onyx.db import web_search as web_search_db

_STORED_URL = "https://api.firecrawl.dev/v2/search"


def test_sibling_base_url_update_keeps_other_config() -> None:
    row = MagicMock()
    row.config = {"base_url": "https://old.example/v2/search", "tbs": "qdr:d"}
    db_session = MagicMock()
    db_session.scalars.return_value.first.return_value = row

    web_search_db.set_web_search_provider_base_url(
        name="Firecrawl", base_url=_STORED_URL, db_session=db_session
    )

    assert row.config == {"base_url": _STORED_URL, "tbs": "qdr:d"}
