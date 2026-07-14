"""Regenerate recommended-models.json from the OpenRouter model catalog.

Applies the curation rules in update_recommended_models_rules.json (trusted
vendors + model-family regexes) to the official OpenRouter catalog
(https://openrouter.ai/api/v1/models) and rewrites
backend/onyx/llm/well_known_providers/recommended-models.json with the newest
matching models per provider section. The rules file is the human-editable
knob: which families are recommendable, how many models to keep, id/display
name overrides, pinned defaults.

The generated file is live production config — deployments poll it from GitHub
raw main (AUTO_LLM_CONFIG_URL) — so this script never pushes anything itself.
The update-recommended-models workflow runs it and opens a reviewed PR, and
that PR's CI is the validation gate: the runtime-schema/Craft-coverage unit
tests and the provider chat tests all run against the regenerated file. The
script itself is standard-library-only on purpose, so any python3 can run it
with no environment setup.

`version`/`updated_at` are bumped only when the model set actually changes, so
deployments' updated_at watermark is not disturbed by cosmetic diffs, and a
re-run against an unchanged catalog produces zero diff.

Usage:
    python backend/scripts/update_recommended_models.py            # check only
    python backend/scripts/update_recommended_models.py --write
"""

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Literal

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_OUTPUT = (
    BACKEND_DIR / "onyx" / "llm" / "well_known_providers" / "recommended-models.json"
)
DEFAULT_RULES = SCRIPT_DIR / "update_recommended_models_rules.json"

IdTransform = Literal["strip_prefix", "strip_prefix_dots_to_dashes", "keep_full_id"]
ID_TRANSFORMS = ("strip_prefix", "strip_prefix_dots_to_dashes", "keep_full_id")


@dataclass
class RecommendedModel:
    name: str
    display_name: str | None = None


@dataclass
class ProviderSection:
    """One provider section, in the on-disk shape of recommended-models.json.

    Deliberately a local mirror rather than the runtime schema
    (LLMRecommendations): CI validates the generated file against the real
    schema post-facto, and staying import-free keeps this script runnable
    with a bare python3.
    """

    default_model: str
    additional_visible_models: list[RecommendedModel]


@dataclass
class RecommendedModelsFile:
    version: str
    updated_at: str
    providers: dict[str, ProviderSection]


@dataclass
class CatalogModel:
    """One entry of the OpenRouter /api/v1/models catalog (fields we use)."""

    id: str
    name: str
    created: int
    pricing: dict[str, Any]
    architecture: dict[str, Any]
    expiration_date: str | None

    @classmethod
    def from_json(cls, entry: dict[str, Any]) -> "CatalogModel":
        return cls(
            id=entry["id"],
            name=entry["name"],
            created=entry.get("created") or 0,
            pricing=entry.get("pricing") or {},
            architecture=entry.get("architecture") or {},
            expiration_date=entry.get("expiration_date"),
        )

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


@dataclass
class FamilyRule:
    """Selects the newest catalog model of one model family."""

    label: str
    vendor_prefix: str
    include_regex: str
    exclude_regex: str | None
    # The rule whose pick becomes the section's default_model.
    is_default_source: bool


@dataclass
class SectionRules:
    """Curation rules for one provider section of recommended-models.json."""

    id_transform: IdTransform
    emit_display_name: bool
    # OpenRouter id -> native model name, taking precedence over id_transform.
    id_overrides: dict[str, str]
    # Native model name -> display name, taking precedence over the
    # catalog-derived display name.
    display_name_overrides: dict[str, str]
    # Forces the section's default_model regardless of what the rules select.
    pinned_default: str | None
    rules: list[FamilyRule]


@dataclass
class CurationRules:
    global_exclude_regex: str
    require_text_output: bool
    sections: dict[str, SectionRules]


def _parse_section_rules(section_name: str, payload: dict[str, Any]) -> SectionRules:
    id_transform = payload["id_transform"]
    if id_transform not in ID_TRANSFORMS:
        raise ValueError(
            f"Section '{section_name}' has unknown id_transform {id_transform!r}"
        )
    return SectionRules(
        id_transform=id_transform,
        emit_display_name=payload.get("emit_display_name", True),
        id_overrides=payload.get("id_overrides") or {},
        display_name_overrides=payload.get("display_name_overrides") or {},
        pinned_default=payload.get("pinned_default"),
        rules=[
            FamilyRule(
                label=rule["label"],
                vendor_prefix=rule["vendor_prefix"],
                include_regex=rule["include_regex"],
                exclude_regex=rule.get("exclude_regex"),
                is_default_source=rule.get("is_default_source", False),
            )
            for rule in payload["rules"]
        ],
    )


def load_rules(path: Path) -> CurationRules:
    payload = json.loads(path.read_text())
    rules = CurationRules(
        global_exclude_regex=payload["global_exclude_regex"],
        require_text_output=payload.get("require_text_output", True),
        sections={
            section_name: _parse_section_rules(section_name, section)
            for section_name, section in payload["sections"].items()
        },
    )
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


def load_previous(path: Path) -> RecommendedModelsFile:
    payload = json.loads(path.read_text())
    return RecommendedModelsFile(
        version=payload["version"],
        updated_at=payload["updated_at"],
        providers={
            section_name: ProviderSection(
                default_model=section["default_model"],
                additional_visible_models=[
                    RecommendedModel(
                        name=model["name"], display_name=model.get("display_name")
                    )
                    for model in section.get("additional_visible_models", [])
                ],
            )
            for section_name, section in payload["providers"].items()
        },
    )


def fetch_catalog(url: str, timeout: float) -> list[CatalogModel]:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Refusing non-HTTP catalog URL: {url!r}")
    request = urllib.request.Request(  # noqa: S310
        url, headers={"Accept": "application/json"}
    )
    # Non-2xx responses raise HTTPError.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read())
    return _parse_catalog(payload)


def load_catalog_file(path: Path) -> list[CatalogModel]:
    return _parse_catalog(json.loads(path.read_text()))


def _parse_catalog(payload: Any) -> list[CatalogModel]:
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("Catalog payload is not a model list")
    return [CatalogModel.from_json(entry) for entry in entries]


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
) -> CatalogModel | None:
    candidates = [
        model
        for model in catalog
        if model.id.startswith(rule.vendor_prefix)
        and re.search(rule.include_regex, model.id)
        and not (rule.exclude_regex and re.search(rule.exclude_regex, model.id))
        and passes_global_filters(model, rules, now)
    ]
    if not candidates:
        return None
    # Never trust API response order: newest wins, id as deterministic tie-break.
    return min(candidates, key=lambda model: (-model.created, model.id))


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


def _strip_vendor_prefix(name: str, model_id: str) -> str:
    """Strip the redundant "Vendor: " prefix from a catalog display name.

    Compares alphanumerics only so "Z.ai: GLM 5.2" matches vendor "z-ai".
    """
    if "/" not in model_id or ": " not in name:
        return name
    prefix, rest = name.split(": ", 1)
    vendor = model_id.split("/")[0]
    normalize = re.compile(r"[^a-z0-9]")
    if normalize.sub("", prefix.lower()) == normalize.sub("", vendor.lower()):
        return rest
    return name


def derive_display_name(
    model: CatalogModel, native_name: str, section: SectionRules
) -> str | None:
    if not section.emit_display_name:
        return None
    override = section.display_name_overrides.get(native_name)
    if override is not None:
        return override
    return _strip_vendor_prefix(model.name, model.id)


def _visible_models(section: ProviderSection | None) -> list[RecommendedModel]:
    if section is None:
        return []
    by_name: dict[str, RecommendedModel] = {}
    for model in [
        RecommendedModel(name=section.default_model),
        *section.additional_visible_models,
    ]:
        existing = by_name.get(model.name)
        if existing is None or (model.display_name and not existing.display_name):
            by_name[model.name] = model
    return list(by_name.values())


def build_section(
    section_name: str,
    section: SectionRules,
    catalog: list[CatalogModel],
    previous: ProviderSection | None,
    rules: CurationRules,
    now: date,
    warnings: list[str],
) -> ProviderSection:
    default_name = section.pinned_default
    picks: list[CatalogModel] = []
    for rule in section.rules:
        pick = select_for_rule(rule, catalog, rules, now)
        if pick is None:
            warnings.append(
                f"{section_name}: rule '{rule.label}' matched no catalog models"
            )
            continue
        picks.append(pick)
        if rule.is_default_source and default_name is None:
            default_name = derive_native_name(pick, section)

    if default_name is None:
        # The default-source rule came up empty and there's no pin: keep the
        # whole section as-is rather than shipping a section without a default.
        if previous is None:
            raise ValueError(
                f"{section_name}: no default model could be selected and there "
                "is no existing section to fall back to"
            )
        warnings.append(
            f"{section_name}: no default model could be selected; keeping the "
            "section unchanged"
        )
        return previous

    models: list[RecommendedModel] = []
    seen_names: set[str] = set()
    for pick in picks:
        native_name = derive_native_name(pick, section)
        if native_name in seen_names:
            continue
        seen_names.add(native_name)
        models.append(
            RecommendedModel(
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
        models.insert(0, RecommendedModel(name=default_name, display_name=display_name))
    else:
        models.insert(0, models.pop(default_index))

    return ProviderSection(
        default_model=default_name,
        additional_visible_models=models,
    )


def _sections_equal(a: ProviderSection, b: ProviderSection) -> bool:
    # Compare the runtime-visible view (the runtime normalizes to default-first
    # and dedupes), not raw file order: a hand-reordered but semantically
    # identical section must not bump version/updated_at.
    def key(section: ProviderSection) -> tuple[Any, ...]:
        return (
            section.default_model,
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
    previous: RecommendedModelsFile,
    today: date,
) -> tuple[RecommendedModelsFile, list[str]]:
    warnings: list[str] = []
    providers = {
        section_name: build_section(
            section_name,
            section,
            catalog,
            previous.providers.get(section_name),
            rules,
            today,
            warnings,
        )
        for section_name, section in rules.sections.items()
    }

    models_changed = set(providers) != set(previous.providers) or any(
        not _sections_equal(new_section, previous.providers[section_name])
        for section_name, new_section in providers.items()
        if section_name in previous.providers
    )
    if not models_changed:
        # Return the previous object untouched so version/updated_at (and the
        # deployments' updated_at watermark) only move on real model changes.
        return previous, warnings

    return (
        RecommendedModelsFile(
            version=_bump_version(previous.version),
            updated_at=f"{today.isoformat()}T00:00:00Z",
            providers=providers,
        ),
        warnings,
    )


def serialize(recommendations: RecommendedModelsFile) -> str:
    providers: dict[str, Any] = {}
    for section_name, section in recommendations.providers.items():
        models: list[dict[str, str]] = []
        for model in section.additional_visible_models:
            entry = {"name": model.name}
            if model.display_name:
                entry["display_name"] = model.display_name
            models.append(entry)
        providers[section_name] = {
            "default_model": section.default_model,
            "additional_visible_models": models,
        }
    data = {
        "version": recommendations.version,
        "updated_at": recommendations.updated_at,
        "providers": providers,
    }
    return json.dumps(data, indent=2) + "\n"


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
    recommendations, warnings = build_recommendations(rules, catalog, previous, today)

    serialized = serialize(recommendations)
    file_stale = serialized != args.output.read_text()

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

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
