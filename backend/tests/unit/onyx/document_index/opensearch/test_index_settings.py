"""Unit tests for index-settings generation (kNN tuning knobs)."""

import pytest

import onyx.document_index.opensearch.schema as os_schema
from onyx.document_index.opensearch.schema import DocumentSchema


def test_default_settings_do_not_touch_derived_source() -> None:
    settings = DocumentSchema.get_index_settings_based_on_environment()["index"]
    assert settings["knn"] is True
    assert "knn.derived_source.enabled" not in settings


def test_derived_source_opt_out_is_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os_schema, "OPENSEARCH_KNN_DERIVED_SOURCE_ENABLED", False)
    settings = DocumentSchema.get_index_settings_based_on_environment()["index"]
    assert settings["knn.derived_source.enabled"] is False
