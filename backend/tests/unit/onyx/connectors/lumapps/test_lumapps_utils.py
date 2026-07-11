"""Unit tests for the LumApps connector's pure helpers (no API / services)."""

from onyx.connectors.lumapps.utils import extract_body_text
from onyx.connectors.lumapps.utils import pick_lang
from onyx.connectors.lumapps.utils import resolve_metadata_labels
from onyx.connectors.lumapps.utils import slugify_family_key


def test_slugify_family_key() -> None:
    assert slugify_family_key("News type") == "news_type"
    assert slugify_family_key("Country") == "country"
    assert slugify_family_key("  Départements / Teams  ") == "d_partements_teams"
    assert slugify_family_key("") == "metadata"


def test_slugify_family_key_non_latin_uses_fallback() -> None:
    """Fully non-Latin names slugify to nothing; the per-family fallback keeps
    distinct families from collapsing into one key."""
    assert slugify_family_key("Страна", fallback="metadata_123") == "metadata_123"
    assert slugify_family_key("部門", fallback="metadata_456") == "metadata_456"
    # distinct families -> distinct keys
    assert slugify_family_key("Страна", fallback="metadata_1") != slugify_family_key(
        "Отдел", fallback="metadata_2"
    )


def test_pick_lang() -> None:
    val = {"en": "Hello", "fr": "Bonjour"}
    assert pick_lang(val, "fr") == "Bonjour"
    assert pick_lang(val, "de") == "Hello"  # fallback to en
    assert pick_lang({"de": "Hallo"}, "fr") == "Hallo"  # any available
    assert pick_lang("plain", "en") == "plain"
    assert pick_lang({}, "en") == ""


def test_extract_body_text_walks_template_widgets() -> None:
    template = {
        "components": [
            {
                "cells": [
                    {
                        "widgets": [
                            {
                                "widgetType": "html",
                                "properties": {
                                    "content": {
                                        "en": "<p>Hello <b>world</b></p>",
                                        "fr": "<p>Bonjour</p>",
                                    }
                                },
                            },
                            {
                                "widgetType": "title",
                                "properties": {"text": "Section A"},
                            },
                            # non-content keys are ignored
                            {"properties": {"styleId": "abc-123", "color": "#fff"}},
                        ]
                    }
                ]
            }
        ]
    }
    body = extract_body_text(template, preferred_lang="en")
    assert "Hello" in body and "world" in body
    assert "Section A" in body
    assert "abc-123" not in body  # style ids are not harvested
    assert "<p>" not in body  # HTML stripped
    # preferred language is chosen
    assert "Bonjour" not in body


def test_extract_body_text_empty() -> None:
    assert extract_body_text(None, "en") == ""
    assert extract_body_text({}, "en") == ""


def test_resolve_metadata_labels_groups_by_family() -> None:
    label_map = {
        "1": ("news_type", "General News"),
        "2": ("departments", "HR"),
        "3": ("departments", "HR"),  # duplicate value
        "4": ("country", "Germany"),
    }
    out = resolve_metadata_labels(["1", "2", "3", "4", "999"], label_map)
    assert out == {
        "news_type": ["General News"],
        "departments": ["HR"],  # de-duplicated
        "country": ["Germany"],
    }
    # unknown ids (999) are skipped
    assert resolve_metadata_labels([], label_map) == {}
