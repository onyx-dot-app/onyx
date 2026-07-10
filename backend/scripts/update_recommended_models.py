"""Regenerate recommended-models.json from the OpenRouter model catalog.

Applies the curation rules in update_recommended_models_rules.json (trusted
vendors + model-family regexes) to the official OpenRouter catalog
(https://openrouter.ai/api/v1/models) and rewrites
backend/onyx/llm/well_known_providers/recommended-models.json with the newest
matching models per provider section. The rules file is the human-editable
knob: which families are recommendable, how many models to keep, id/display
name overrides, pinned defaults.

The generated file is live production config — deployments poll it from GitHub
raw main (AUTO_LLM_CONFIG_URL) — so this script never pushes anything itself;
the update-recommended-models workflow runs it and opens a reviewed PR.

`version`/`updated_at` are bumped only when the model set actually changes, so
deployments' updated_at watermark is not disturbed by cosmetic diffs, and a
re-run against an unchanged catalog produces zero diff.

Usage:
    python backend/scripts/update_recommended_models.py            # check only
    python backend/scripts/update_recommended_models.py --write
    python backend/scripts/update_recommended_models.py --write \
        --summary-file /tmp/summary.md
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Literal

import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

# Ensure PYTHONPATH is set up for direct script execution
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.append(str(BACKEND_DIR))

from onyx.llm.well_known_providers.auto_update_models import (  # noqa: E402
    LLMProviderRecommendation,
)
from onyx.llm.well_known_providers.auto_update_models import (  # noqa: E402
    LLMRecommendations,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel  # noqa: E402
from onyx.server.features.build.configs import (  # noqa: E402
    BUILD_MODE_ALLOWED_PROVIDER_TYPES,
)
from onyx.server.manage.llm.utils import strip_openrouter_vendor_prefix  # noqa: E402

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_OUTPUT = (
    BACKEND_DIR / "onyx" / "llm" / "well_known_providers" / "recommended-models.json"
)
DEFAULT_RULES = SCRIPT_DIR / "update_recommended_models_rules.json"
DEFAULT_ENRICHMENTS = BACKEND_DIR / "onyx" / "llm" / "model_metadata_enrichments.json"


class CatalogModel(BaseModel):
    """One entry of the OpenRouter /api/v1/models catalog (fields we use)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    created: int = 0
    pricing: dict[str, Any] = Field(default_factory=dict)
    architecture: dict[str, Any] = Field(default_factory=dict)
    expiration_date: str | None = None

    @property
    def output_modalities(self) -> list[str]:
        value = self.architecture.get("output_modalities")
        return value if isinstance(value, list) else []

    @property
    def is_free(self) -> bool:
        if self.id.endswith(":free"):
            return True
        return (
            self.pricing.get("prompt") == "0" and self.pricing.get("completion") == "0"
        )

    def is_expired(self, now: date) -> bool:
        if not self.expiration_date:
            return False
        try:
            return date.fromisoformat(self.expiration_date) <= now
        except ValueError:
            return False


IdTransform = Literal["strip_prefix", "strip_prefix_dots_to_dashes", "keep_full_id"]


class FamilyRule(BaseModel):
    """Selects the newest N catalog models of one model family."""

    label: str
    vendor_prefix: str
    include_regex: str
    exclude_regex: str | None = None
    limit: int = 1
    # The rule whose newest pick becomes the section's default_model.
    is_default_source: bool = False


class SectionRules(BaseModel):
    """Curation rules for one provider section of recommended-models.json."""

    id_transform: IdTransform
    # False => every model added to this section is flagged for human
    # verification in the summary (the OpenRouter id -> native id mapping is a
    # heuristic for this provider).
    transform_is_reliable: bool = True
    emit_display_name: bool = True
    # OpenRouter id -> native model name, taking precedence over id_transform.
    id_overrides: dict[str, str] = Field(default_factory=dict)
    # Native model name -> display name, taking precedence over the
    # catalog-derived display name.
    display_name_overrides: dict[str, str] = Field(default_factory=dict)
    # Forces the section's default_model regardless of what the rules select.
    pinned_default: str | None = None
    rules: list[FamilyRule]


class CurationRules(BaseModel):
    global_exclude_regex: str
    require_text_output: bool = True
    sections: dict[str, SectionRules]


@dataclass
class ChangeReport:
    # True when the model set differs from the current file (as opposed to a
    # formatting-only rewrite).
    models_changed: bool = False
    added: dict[str, list[str]] = field(default_factory=dict)
    removed: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    enrichment_gaps: list[str] = field(default_factory=list)


def load_rules(path: Path) -> CurationRules:
    rules = CurationRules.model_validate(json.loads(path.read_text()))
    for section_name, section in rules.sections.items():
        default_sources = [r.label for r in section.rules if r.is_default_source]
        if len(default_sources) > 1:
            raise ValueError(
                f"Section '{section_name}' has multiple default-source rules: "
                f"{default_sources}"
            )
        if not default_sources and section.pinned_default is None:
            raise ValueError(
                f"Section '{section_name}' needs a rule with is_default_source "
                "or a pinned_default"
            )
    return rules


def load_previous(path: Path) -> LLMRecommendations:
    return LLMRecommendations.model_validate(json.loads(path.read_text()))


def fetch_catalog(url: str, timeout: float) -> list[CatalogModel]:
    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    return _parse_catalog(response.json())


def load_catalog_file(path: Path) -> list[CatalogModel]:
    return _parse_catalog(json.loads(path.read_text()))


def _parse_catalog(payload: Any) -> list[CatalogModel]:
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("Catalog payload is not a model list")
    return [CatalogModel.model_validate(entry) for entry in entries]


def passes_global_filters(model: CatalogModel, rules: CurationRules, now: date) -> bool:
    if re.search(rules.global_exclude_regex, model.id):
        return False
    if model.is_free:
        return False
    if model.is_expired(now):
        return False
    if rules.require_text_output and "text" not in model.output_modalities:
        return False
    return True


def select_for_rule(
    rule: FamilyRule,
    catalog: list[CatalogModel],
    rules: CurationRules,
    now: date,
) -> list[CatalogModel]:
    candidates = [
        model
        for model in catalog
        if model.id.startswith(rule.vendor_prefix)
        and re.search(rule.include_regex, model.id)
        and not (rule.exclude_regex and re.search(rule.exclude_regex, model.id))
        and passes_global_filters(model, rules, now)
    ]
    # Never trust API response order: newest first, id as deterministic tie-break.
    candidates.sort(key=lambda model: (-model.created, model.id))
    return candidates[: rule.limit]


def derive_native_name(model: CatalogModel, section: SectionRules) -> str:
    override = section.id_overrides.get(model.id)
    if override is not None:
        return override
    if section.id_transform == "keep_full_id":
        return model.id
    bare = model.id.split("/", 1)[1] if "/" in model.id else model.id
    if section.id_transform == "strip_prefix_dots_to_dashes":
        return bare.replace(".", "-")
    return bare


def _clean_display_name(name: str, model_id: str) -> str:
    """Strip the redundant "Vendor: " prefix from a catalog display name.

    Falls back to an alphanumeric-only comparison for vendors the shared
    helper's normalization misses (e.g. "Z.ai: GLM 5.1" vs vendor "z-ai").
    """
    stripped = strip_openrouter_vendor_prefix(name, model_id)
    if stripped != name or "/" not in model_id or ": " not in name:
        return stripped
    prefix, rest = name.split(": ", 1)
    vendor = model_id.split("/")[0]
    normalize = re.compile(r"[^a-z0-9]")
    if normalize.sub("", prefix.lower()) == normalize.sub("", vendor.lower()):
        return rest
    return stripped


def derive_display_name(
    model: CatalogModel, native_name: str, section: SectionRules
) -> str | None:
    if not section.emit_display_name:
        return None
    override = section.display_name_overrides.get(native_name)
    if override is not None:
        return override
    return _clean_display_name(model.name, model.id)


def _visible_models(
    section: LLMProviderRecommendation | None,
) -> list[SimpleKnownModel]:
    if section is None:
        return []
    by_name: dict[str, SimpleKnownModel] = {}
    for model in [section.default_model, *section.additional_visible_models]:
        existing = by_name.get(model.name)
        if existing is None or (model.display_name and not existing.display_name):
            by_name[model.name] = model
    return list(by_name.values())


def build_section(
    section_name: str,
    section: SectionRules,
    catalog: list[CatalogModel],
    previous: LLMProviderRecommendation | None,
    rules: CurationRules,
    now: date,
    report: ChangeReport,
) -> LLMProviderRecommendation:
    default_name = section.pinned_default
    picks: list[CatalogModel] = []
    for rule in section.rules:
        matches = select_for_rule(rule, catalog, rules, now)
        if not matches:
            report.warnings.append(
                f"{section_name}: rule '{rule.label}' matched no catalog models"
            )
        picks.extend(matches)
        if rule.is_default_source and default_name is None and matches:
            default_name = derive_native_name(matches[0], section)

    if default_name is None:
        # The default-source rule came up empty and there's no pin: keep the
        # whole section as-is rather than shipping a section without a default.
        if previous is None:
            raise ValueError(
                f"{section_name}: no default model could be selected and there "
                "is no existing section to fall back to"
            )
        report.warnings.append(
            f"{section_name}: no default model could be selected; keeping the "
            "section unchanged"
        )
        return previous

    models: list[SimpleKnownModel] = []
    native_to_catalog_id: dict[str, str] = {}
    for pick in picks:
        native_name = derive_native_name(pick, section)
        if native_name in native_to_catalog_id:
            continue
        native_to_catalog_id[native_name] = pick.id
        models.append(
            SimpleKnownModel(
                name=native_name,
                display_name=derive_display_name(pick, native_name, section),
            )
        )

    default_index = next(
        (i for i, model in enumerate(models) if model.name == default_name), None
    )
    if default_index is None:
        display_name: str | None = None
        if section.emit_display_name:
            previous_display = {
                model.name: model.display_name for model in _visible_models(previous)
            }
            display_name = section.display_name_overrides.get(
                default_name
            ) or previous_display.get(default_name)
        models.insert(0, SimpleKnownModel(name=default_name, display_name=display_name))
    else:
        models.insert(0, models.pop(default_index))

    if not section.transform_is_reliable:
        previous_names = {model.name for model in _visible_models(previous)}
        for model in models:
            catalog_id = native_to_catalog_id.get(model.name)
            if model.name not in previous_names and catalog_id is not None:
                report.unverified.append(
                    f"{section_name}: `{catalog_id}` → `{model.name}` — the id "
                    "mapping is heuristic; verify against the provider's native "
                    "model ids"
                )

    return LLMProviderRecommendation(
        default_model=SimpleKnownModel(name=default_name),
        additional_visible_models=models,
    )


def _sections_equal(a: LLMProviderRecommendation, b: LLMProviderRecommendation) -> bool:
    # Compare the runtime-visible view (get_visible_models normalizes to
    # default-first and dedupes), not raw file order: a hand-reordered but
    # semantically identical section must not bump version/updated_at.
    def key(section: LLMProviderRecommendation) -> tuple[Any, ...]:
        return (
            section.default_model.name,
            tuple(
                (model.name, model.display_name) for model in _visible_models(section)
            ),
        )

    return key(a) == key(b)


def _bump_version(version: str) -> str:
    parts = version.split(".")
    if not parts[-1].isdigit():
        raise ValueError(f"Cannot bump non-numeric version {version!r}")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def build_recommendations(
    rules: CurationRules,
    catalog: list[CatalogModel],
    previous: LLMRecommendations,
    today: date,
) -> tuple[LLMRecommendations, ChangeReport]:
    report = ChangeReport()
    providers = {
        section_name: build_section(
            section_name,
            section,
            catalog,
            previous.providers.get(section_name),
            rules,
            today,
            report,
        )
        for section_name, section in rules.sections.items()
    }

    for section_name, new_section in providers.items():
        previous_names = [
            model.name
            for model in _visible_models(previous.providers.get(section_name))
        ]
        new_names = [model.name for model in _visible_models(new_section)]
        added = [name for name in new_names if name not in previous_names]
        removed = [name for name in previous_names if name not in new_names]
        if added:
            report.added[section_name] = added
        if removed:
            report.removed[section_name] = removed

    report.models_changed = set(providers) != set(previous.providers) or any(
        not _sections_equal(new_section, previous.providers[section_name])
        for section_name, new_section in providers.items()
        if section_name in previous.providers
    )
    if not report.models_changed:
        # Return the previous object untouched so version/updated_at (and the
        # deployments' updated_at watermark) only move on real model changes.
        return previous, report

    return (
        LLMRecommendations(
            version=_bump_version(previous.version),
            updated_at=datetime(
                today.year, today.month, today.day, tzinfo=timezone.utc
            ),
            providers=providers,
        ),
        report,
    )


def check_build_mode_coverage(recommendations: LLMRecommendations) -> None:
    """Mirror of test_recommended_config_covers_allowed_provider_types."""
    missing = [
        provider_type
        for provider_type in BUILD_MODE_ALLOWED_PROVIDER_TYPES
        if recommendations.get_default_model(provider_type) is None
    ]
    if missing:
        raise ValueError(
            "Generated config is missing a default_model for Craft-supported "
            f"provider types: {missing}"
        )


def check_enrichment_gaps(
    new: LLMRecommendations,
    previous: LLMRecommendations,
    enrichments_path: Path,
) -> list[str]:
    """Advisory: newly added model names without a model_metadata_enrichments
    entry fall back to default token limits / vision=False."""
    if not enrichments_path.exists():
        return []
    enrichment_keys: set[str] = set(json.loads(enrichments_path.read_text()).keys())

    def has_entry(name: str) -> bool:
        return name in enrichment_keys or any(
            key.endswith(f"/{name}") for key in enrichment_keys
        )

    gaps = []
    for section_name, section in new.providers.items():
        previous_names = {
            model.name
            for model in _visible_models(previous.providers.get(section_name))
        }
        for model in _visible_models(section):
            if model.name not in previous_names and not has_entry(model.name):
                gaps.append(f"{section_name}: `{model.name}`")
    return gaps


def serialize(recommendations: LLMRecommendations) -> str:
    updated_at = recommendations.updated_at
    if updated_at.tzinfo is not None:
        updated_at = updated_at.astimezone(timezone.utc)
    providers: dict[str, Any] = {}
    for section_name, section in recommendations.providers.items():
        models: list[dict[str, str]] = []
        for model in section.additional_visible_models:
            entry = {"name": model.name}
            if model.display_name:
                entry["display_name"] = model.display_name
            models.append(entry)
        providers[section_name] = {
            "default_model": section.default_model.name,
            "additional_visible_models": models,
        }
    data = {
        "version": recommendations.version,
        "updated_at": updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "providers": providers,
    }
    text = json.dumps(data, indent=2) + "\n"
    # Self-check: the file we write must round-trip through the runtime schema.
    LLMRecommendations.model_validate(json.loads(text))
    return text


def render_summary(report: ChangeReport, file_stale: bool) -> str:
    lines = ["## Recommended models update", ""]
    if report.models_changed:
        for section_name in sorted(set(report.added) | set(report.removed)):
            lines.append(f"### {section_name}")
            for name in report.added.get(section_name, []):
                lines.append(f"- Added: `{name}`")
            for name in report.removed.get(section_name, []):
                lines.append(f"- Removed: `{name}`")
            lines.append("")
    elif file_stale:
        lines.extend(["No model changes — formatting normalization only.", ""])
    else:
        lines.extend(["No changes.", ""])
    if report.unverified:
        lines.append("### ⚠️ Verify model ids")
        lines.extend(f"- {item}" for item in report.unverified)
        lines.append("")
    if report.enrichment_gaps:
        lines.append("### Notices")
        lines.append(
            "Newly added models without a `model_metadata_enrichments.json` "
            "entry (they fall back to default token limits / no vision):"
        )
        lines.extend(f"- {item}" for item in report.enrichment_gaps)
        lines.append("")
    if report.warnings:
        lines.append("### Warnings")
        lines.extend(f"- {item}" for item in report.warnings)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite the recommended-models file (default: check only)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the file is stale without writing (the default)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--catalog-url", default=OPENROUTER_MODELS_URL)
    parser.add_argument(
        "--catalog-file",
        type=Path,
        default=None,
        help="Read the catalog from a JSON file instead of the API",
    )
    parser.add_argument("--enrichments", type=Path, default=DEFAULT_ENRICHMENTS)
    parser.add_argument(
        "--summary-file",
        type=Path,
        default=None,
        help="Write a markdown change summary (used as the PR body)",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.write and args.check:
        parser.error("--write and --check are mutually exclusive")

    rules = load_rules(args.rules)
    previous = load_previous(args.output)
    catalog = (
        load_catalog_file(args.catalog_file)
        if args.catalog_file
        else fetch_catalog(args.catalog_url, args.timeout)
    )

    today = datetime.now(tz=timezone.utc).date()
    recommendations, report = build_recommendations(rules, catalog, previous, today)
    check_build_mode_coverage(recommendations)
    report.enrichment_gaps = check_enrichment_gaps(
        recommendations, previous, args.enrichments
    )

    serialized = serialize(recommendations)
    file_stale = serialized != args.output.read_text()

    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if args.summary_file:
        args.summary_file.write_text(render_summary(report, file_stale))

    if not file_stale:
        print(f"{args.output} is up to date.")
        return 0
    if args.write:
        args.output.write_text(serialized)
        print(f"Updated {args.output}")
        return 0
    print(f"{args.output} is stale (re-run with --write).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
