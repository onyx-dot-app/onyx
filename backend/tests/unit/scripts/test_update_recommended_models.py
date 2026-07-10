"""Unit tests for the recommended-models generator script.

The generated file is live production config (deployments poll it from GitHub
raw main), so the selection, id-mapping, idempotency, and serialization
behaviors are worth locking down against fixture catalogs.
"""

import json
from datetime import date
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest
from scripts.update_recommended_models import build_recommendations
from scripts.update_recommended_models import build_section
from scripts.update_recommended_models import CatalogModel
from scripts.update_recommended_models import ChangeReport
from scripts.update_recommended_models import check_build_mode_coverage
from scripts.update_recommended_models import check_enrichment_gaps
from scripts.update_recommended_models import CurationRules
from scripts.update_recommended_models import DEFAULT_RULES
from scripts.update_recommended_models import derive_display_name
from scripts.update_recommended_models import derive_native_name
from scripts.update_recommended_models import FamilyRule
from scripts.update_recommended_models import load_rules
from scripts.update_recommended_models import main
from scripts.update_recommended_models import render_summary
from scripts.update_recommended_models import SectionRules
from scripts.update_recommended_models import select_for_rule
from scripts.update_recommended_models import serialize

from onyx.llm.well_known_providers.auto_update_models import LLMProviderRecommendation
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations

TODAY = date(2026, 7, 10)


def _cat(
    model_id: str,
    name: str,
    created: int,
    output: tuple[str, ...] = ("text",),
    pricing: dict[str, str] | None = None,
    expiration_date: str | None = None,
) -> CatalogModel:
    return CatalogModel(
        id=model_id,
        name=name,
        created=created,
        pricing=pricing or {"prompt": "0.000001", "completion": "0.000002"},
        architecture={"output_modalities": list(output)},
        expiration_date=expiration_date,
    )


def _rules(sections: dict[str, SectionRules]) -> CurationRules:
    return CurationRules(
        global_exclude_regex="(:free$)|(embedding)",
        require_text_output=True,
        sections=sections,
    )


def _section(
    rules: list[FamilyRule],
    id_transform: str = "keep_full_id",
    **kwargs: Any,
) -> SectionRules:
    return SectionRules.model_validate(
        {"id_transform": id_transform, "rules": [r.model_dump() for r in rules]}
        | kwargs
    )


def _rule(
    label: str = "family",
    vendor_prefix: str = "acme/",
    include_regex: str = r"^acme/model-\d+(\.\d+)?$",
    **kwargs: Any,
) -> FamilyRule:
    return FamilyRule(
        label=label,
        vendor_prefix=vendor_prefix,
        include_regex=include_regex,
        **kwargs,
    )


def test_select_for_rule_newest_n_with_deterministic_tie_break() -> None:
    catalog = [
        _cat("acme/model-1", "Acme: Model 1", 100),
        _cat("acme/model-3", "Acme: Model 3", 300),
        _cat("acme/model-2b", "Acme: Model 2b", 200),
        _cat("acme/model-2a", "Acme: Model 2a", 200),
    ]
    rule = _rule(include_regex=r"^acme/model-\d+[ab]?$", limit=3)
    picks = select_for_rule(rule, catalog, _rules({}), TODAY)
    assert [m.id for m in picks] == ["acme/model-3", "acme/model-2a", "acme/model-2b"]


def test_select_for_rule_exclude_regex_beats_include() -> None:
    catalog = [
        _cat("acme/model-6-luna", "Acme: Model 6 Luna", 300),
        _cat("acme/model-5", "Acme: Model 5", 200),
    ]
    rule = _rule(
        include_regex=r"^acme/model-\d+", exclude_regex="-(luna|terra)", limit=1
    )
    picks = select_for_rule(rule, catalog, _rules({}), TODAY)
    assert [m.id for m in picks] == ["acme/model-5"]


@pytest.mark.parametrize(
    "model",
    [
        _cat("acme/model-9:free", "Acme: Model 9 (free)", 900),
        _cat(
            "acme/model-9",
            "Acme: Model 9",
            900,
            pricing={"prompt": "0", "completion": "0"},
        ),
        _cat("acme/model-9", "Acme: Model 9", 900, output=("image",)),
        _cat("acme/model-9", "Acme: Model 9", 900, expiration_date="2026-01-01"),
        _cat("acme/model-9-embedding", "Acme: Embedding 9", 900),
    ],
)
def test_global_filters_exclude(model: CatalogModel) -> None:
    rule = _rule(include_regex="^acme/model-9")
    assert select_for_rule(rule, [model], _rules({}), TODAY) == []


def test_derive_native_name_id_override_wins() -> None:
    section = _section(
        [_rule()],
        id_transform="strip_prefix",
        id_overrides={"acme/model-1": "custom-name-1"},
    )
    assert derive_native_name(_cat("acme/model-1", "M1", 1), section) == "custom-name-1"
    assert derive_native_name(_cat("acme/model-2", "M2", 2), section) == "model-2"


def test_derive_native_name_dots_to_dashes() -> None:
    section = _section([_rule()], id_transform="strip_prefix_dots_to_dashes")
    model = _cat("anthropic/claude-opus-4.8", "Anthropic: Claude Opus 4.8", 1)
    assert derive_native_name(model, section) == "claude-opus-4-8"


def test_derive_display_name() -> None:
    model = _cat("z-ai/glm-5.1", "Z.ai: GLM 5.1", 1)
    disabled = _section([_rule()], emit_display_name=False)
    assert derive_display_name(model, "z-ai/glm-5.1", disabled) is None

    enabled = _section([_rule()])
    # Vendor prefix stripped even when normalization needs the alnum fallback
    # ("Z.ai" vs vendor "z-ai").
    assert derive_display_name(model, "z-ai/glm-5.1", enabled) == "GLM 5.1"

    overridden = _section(
        [_rule()], display_name_overrides={"z-ai/glm-5.1": "GLM Five"}
    )
    assert derive_display_name(model, "z-ai/glm-5.1", overridden) == "GLM Five"


def _previous_section(
    default: str, models: list[tuple[str, str | None]]
) -> LLMProviderRecommendation:
    return LLMProviderRecommendation.model_validate(
        {
            "default_model": default,
            "additional_visible_models": [
                {"name": name, **({"display_name": dn} if dn else {})}
                for name, dn in models
            ],
        }
    )


def test_build_section_default_first_and_deduped_across_rules() -> None:
    catalog = [
        _cat("acme/model-2", "Acme: Model 2", 200),
        _cat("acme/model-1", "Acme: Model 1", 100),
    ]
    # Both rules match model-2; the second rule's pick makes it the default.
    section = _section(
        [
            _rule(label="all", include_regex=r"^acme/model-\d+$", limit=2),
            _rule(
                label="default",
                include_regex=r"^acme/model-2$",
                is_default_source=True,
            ),
        ]
    )
    report = ChangeReport()
    result = build_section("test", section, catalog, None, _rules({}), TODAY, report)
    assert result.default_model.name == "acme/model-2"
    assert [m.name for m in result.additional_visible_models] == [
        "acme/model-2",
        "acme/model-1",
    ]


def test_build_section_keeps_previous_when_default_source_empty() -> None:
    previous = _previous_section("old-default", [("old-default", None)])
    section = _section(
        [_rule(include_regex="^acme/nonexistent$", is_default_source=True)]
    )
    report = ChangeReport()
    result = build_section("test", section, [], previous, _rules({}), TODAY, report)
    assert result is previous
    assert any("keeping the section unchanged" in w for w in report.warnings)


def test_build_section_non_default_rule_empty_just_warns() -> None:
    catalog = [_cat("acme/model-1", "Acme: Model 1", 100)]
    section = _section(
        [
            _rule(label="main", is_default_source=True),
            _rule(label="gone", include_regex="^acme/nonexistent$"),
        ]
    )
    report = ChangeReport()
    result = build_section("test", section, catalog, None, _rules({}), TODAY, report)
    assert [m.name for m in result.additional_visible_models] == ["acme/model-1"]
    assert any("'gone' matched no catalog models" in w for w in report.warnings)


def test_build_section_pinned_default_inserted_first() -> None:
    catalog = [_cat("acme/model-1", "Acme: Model 1", 100)]
    section = _section([_rule()], pinned_default="acme/pinned")
    report = ChangeReport()
    result = build_section("test", section, catalog, None, _rules({}), TODAY, report)
    assert result.default_model.name == "acme/pinned"
    assert [m.name for m in result.additional_visible_models] == [
        "acme/pinned",
        "acme/model-1",
    ]


def test_build_section_flags_unverified_mappings_for_new_models() -> None:
    previous = _previous_section("claude-opus-4-8", [("claude-opus-4-8", None)])
    catalog = [
        _cat("anthropic/claude-opus-4.9", "Anthropic: Claude Opus 4.9", 200),
    ]
    section = _section(
        [
            _rule(
                vendor_prefix="anthropic/",
                include_regex=r"^anthropic/claude-opus-\d+(\.\d+)?$",
                is_default_source=True,
            )
        ],
        id_transform="strip_prefix_dots_to_dashes",
        transform_is_reliable=False,
    )
    report = ChangeReport()
    build_section("anthropic", section, catalog, previous, _rules({}), TODAY, report)
    assert len(report.unverified) == 1
    assert "`anthropic/claude-opus-4.9` → `claude-opus-4-9`" in report.unverified[0]


def _simple_setup() -> tuple[CurationRules, list[CatalogModel], LLMRecommendations]:
    rules = _rules(
        {
            "openrouter": _section(
                [_rule(include_regex=r"^acme/model-\d+$", is_default_source=True)]
            )
        }
    )
    catalog = [_cat("acme/model-1", "Acme: Model 1", 100)]
    previous = LLMRecommendations.model_validate(
        {
            "version": "1.4",
            "updated_at": "2026-06-04T00:00:00Z",
            "providers": {
                "openrouter": {
                    "default_model": "acme/model-1",
                    "additional_visible_models": [
                        {"name": "acme/model-1", "display_name": "Model 1"}
                    ],
                }
            },
        }
    )
    return rules, catalog, previous


def test_build_recommendations_no_change_returns_previous_untouched() -> None:
    rules, catalog, previous = _simple_setup()
    result, report = build_recommendations(rules, catalog, previous, TODAY)
    assert result is previous
    assert not report.models_changed
    assert report.added == {} and report.removed == {}


def test_build_recommendations_bumps_version_on_model_change() -> None:
    rules, catalog, previous = _simple_setup()
    catalog.append(_cat("acme/model-2", "Acme: Model 2", 200))
    result, report = build_recommendations(rules, catalog, previous, TODAY)
    assert report.models_changed
    assert result.version == "1.5"
    assert result.updated_at == datetime(2026, 7, 10, tzinfo=timezone.utc)
    assert report.added == {"openrouter": ["acme/model-2"]}
    assert report.removed == {"openrouter": ["acme/model-1"]}


def test_serialize_golden() -> None:
    recs = LLMRecommendations.model_validate(
        {
            "version": "1.4",
            "updated_at": "2026-06-04T00:00:00Z",
            "providers": {
                "openai": {
                    "default_model": "gpt-5.5",
                    "additional_visible_models": [
                        {"name": "gpt-5.5"},
                        {"name": "gpt-5.4"},
                    ],
                },
                "openrouter": {
                    "default_model": "z-ai/glm-5.1",
                    "additional_visible_models": [
                        {"name": "z-ai/glm-5.1", "display_name": "GLM 5.1"}
                    ],
                },
            },
        }
    )
    expected = (
        "{\n"
        '  "version": "1.4",\n'
        '  "updated_at": "2026-06-04T00:00:00Z",\n'
        '  "providers": {\n'
        '    "openai": {\n'
        '      "default_model": "gpt-5.5",\n'
        '      "additional_visible_models": [\n'
        "        {\n"
        '          "name": "gpt-5.5"\n'
        "        },\n"
        "        {\n"
        '          "name": "gpt-5.4"\n'
        "        }\n"
        "      ]\n"
        "    },\n"
        '    "openrouter": {\n'
        '      "default_model": "z-ai/glm-5.1",\n'
        '      "additional_visible_models": [\n'
        "        {\n"
        '          "name": "z-ai/glm-5.1",\n'
        '          "display_name": "GLM 5.1"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    serialized = serialize(recs)
    assert serialized == expected
    round_tripped = LLMRecommendations.model_validate(json.loads(serialized))
    assert round_tripped == recs


def test_check_build_mode_coverage_raises_on_missing_craft_provider() -> None:
    recs = LLMRecommendations.model_validate(
        {
            "version": "1.0",
            "updated_at": "2026-06-04T00:00:00Z",
            "providers": {
                "openai": {"default_model": "gpt-5.5"},
                "anthropic": {"default_model": "claude-opus-4-8"},
                # openrouter missing
            },
        }
    )
    with pytest.raises(ValueError, match="openrouter"):
        check_build_mode_coverage(recs)


def test_check_enrichment_gaps_flags_only_new_models(tmp_path: Path) -> None:
    enrichments = tmp_path / "enrichments.json"
    enrichments.write_text(
        json.dumps({"model-known": {}, "openrouter/acme/model-prefixed": {}})
    )
    previous = LLMRecommendations.model_validate(
        {
            "version": "1.0",
            "updated_at": "2026-06-04T00:00:00Z",
            "providers": {"openai": {"default_model": "model-old"}},
        }
    )
    new = LLMRecommendations.model_validate(
        {
            "version": "1.1",
            "updated_at": "2026-07-10T00:00:00Z",
            "providers": {
                "openai": {
                    "default_model": "model-known",
                    "additional_visible_models": [
                        {"name": "model-known"},
                        {"name": "acme/model-prefixed"},
                        {"name": "model-old"},
                        {"name": "model-unknown"},
                    ],
                }
            },
        }
    )
    gaps = check_enrichment_gaps(new, previous, enrichments)
    # model-known has an exact entry, model-prefixed a suffix entry, model-old
    # is not newly added — only model-unknown is a gap.
    assert gaps == ["openai: `model-unknown`"]


def test_render_summary_lists_changes_per_provider() -> None:
    report = ChangeReport(
        models_changed=True,
        added={"openrouter": ["acme/model-2"]},
        removed={"openrouter": ["acme/model-1"]},
        unverified=["anthropic: `a/b-1.2` → `b-1-2` — verify"],
        enrichment_gaps=["openrouter: `acme/model-2`"],
        warnings=["something odd"],
    )
    summary = render_summary(report, file_stale=True)
    assert "- Added: `acme/model-2`" in summary
    assert "- Removed: `acme/model-1`" in summary
    assert "Verify model ids" in summary
    assert "something odd" in summary


def test_shipped_rules_file_is_valid() -> None:
    rules = load_rules(DEFAULT_RULES)
    assert set(rules.sections) == {"openai", "anthropic", "vertex_ai", "openrouter"}


def _write_cli_fixtures(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Rules/catalog/output covering every Craft provider type."""
    sections = {
        name: _section(
            [
                _rule(
                    vendor_prefix=f"{vendor}/",
                    include_regex=rf"^{vendor}/model-\d+$",
                    is_default_source=True,
                )
            ],
            emit_display_name=False,
        ).model_dump()
        for name, vendor in [
            ("openai", "openai"),
            ("anthropic", "anthropic"),
            ("openrouter", "acme"),
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "global_exclude_regex": ":free$",
                "require_text_output": True,
                "sections": sections,
            }
        )
    )
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "data": [
                    _cat(f"{vendor}/model-{version}", "Model", version).model_dump()
                    for vendor in ["openai", "anthropic", "acme"]
                    for version in [1, 2]
                ]
            }
        )
    )
    output_path = tmp_path / "recommended-models.json"
    output_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "updated_at": "2026-06-04T00:00:00Z",
                "providers": {
                    name: {
                        "default_model": f"{vendor}/model-1",
                        "additional_visible_models": [{"name": f"{vendor}/model-1"}],
                    }
                    for name, vendor in [
                        ("openai", "openai"),
                        ("anthropic", "anthropic"),
                        ("openrouter", "acme"),
                    ]
                },
            }
        )
    )
    return rules_path, catalog_path, output_path


def _cli_args(rules: Path, catalog: Path, output: Path) -> list[str]:
    return [
        "--rules",
        str(rules),
        "--catalog-file",
        str(catalog),
        "--output",
        str(output),
        "--enrichments",
        str(output.parent / "missing-enrichments.json"),
    ]


def test_cli_check_exits_1_without_writing(tmp_path: Path) -> None:
    rules, catalog, output = _write_cli_fixtures(tmp_path)
    original = output.read_text()
    assert main(["--check", *_cli_args(rules, catalog, output)]) == 1
    assert output.read_text() == original


def test_cli_write_is_idempotent(tmp_path: Path) -> None:
    rules, catalog, output = _write_cli_fixtures(tmp_path)
    assert main(["--write", *_cli_args(rules, catalog, output)]) == 0
    written = output.read_text()
    assert written.endswith("\n")
    updated = LLMRecommendations.model_validate(json.loads(written))
    # model-2 is newer, so it becomes the default everywhere and bumps version.
    assert updated.version == "1.1"
    default = updated.get_default_model("openrouter")
    assert default is not None
    assert default.name == "acme/model-2"

    # Second run: no catalog change -> no diff, clean exit in check mode too.
    assert main(["--write", *_cli_args(rules, catalog, output)]) == 0
    assert output.read_text() == written
    assert main(["--check", *_cli_args(rules, catalog, output)]) == 0
