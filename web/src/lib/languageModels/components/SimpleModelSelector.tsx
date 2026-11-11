"use client";

import { useProviderNames } from "@/lib/languageModels/useProviderNames";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  InputSingleSelect,
  type InputSingleSelectProps,
} from "@opal/components";
import type {
  SelectOption,
  SelectOptions,
} from "@opal/components/inputs/dropdowns/types";
import { optionMatchesSearch } from "@opal/components/dropdown/model";
import {
  buildModelSelectOptions,
  fromSelectValue,
  toSelectValue,
} from "@/lib/languageModels/options";
import { getModelIcon } from "@/lib/languageModels/utils";
import type {
  ModelOptionProvider,
  ModelPaging,
} from "@/lib/languageModels/types";

/** The select value of the Global Default row; `fromSelectValue` reads it as null. */
const GLOBAL_DEFAULT_SELECT_VALUE = "global-default";

/** Prefixes a decision-section row's select value, so a model listed among
 *  both decision and language models has two distinct rows. */
const DECISION_SELECT_PREFIX = "decision:";

/** A keystroke storm settles before a search leaves for the server. */
export const SERVER_SEARCH_DEBOUNCE_MS = 300;

/**
 * True when a loaded row matches the query. A provider title match does not
 * count: it shows only that provider's loaded rows, so the server is still
 * asked for the rest.
 */
function hasLoadedMatch(options: SelectOptions, query: string): boolean {
  const term = query.toLowerCase();
  return options.some((item) =>
    "options" in item
      ? item.options.some((opt) => optionMatchesSearch(opt, term))
      : optionMatchesSearch(item, term)
  );
}

function hasOptionValue(options: SelectOptions, value: string): boolean {
  return options.some((item) =>
    "options" in item
      ? item.options.some((opt) => opt.value === value)
      : item.value === value
  );
}

export interface GlobalDefaultRow {
  /** The row's title, when "Global Default" is not the right name. */
  label?: string;
  /** The model null resolves to, shown under the row's title. */
  description?: string | null;
}

export interface DecisionSection {
  /** The section's divider title. */
  title: string;
  providers: ModelOptionProvider[];
  /** True when `value` is one of this section's models. */
  selected: boolean;
  /** Called instead of `onChange` when a row of this section is picked. */
  onChange: (modelConfigurationId: number) => void;
}

/** What `onChange` emits: only a nullable selector can emit null. */
type EmittedModelConfigurationId<Nullable extends boolean> =
  Nullable extends true ? number | null : number;

export interface SimpleModelSelectorProps<Nullable extends boolean = false> {
  includeDecisionOnly?: boolean;
  providers: ModelOptionProvider[];
  /** The chosen model configuration id; null shows the placeholder. */
  value: number | null;
  onChange: (
    modelConfigurationId: EmittedModelConfigurationId<Nullable>
  ) => void;
  /**
   * When true, null is a real state the user can return to: re-picking the
   * chosen model clears it. Otherwise a chosen model is a floor, a re-pick
   * does nothing, and `onChange` never emits null.
   */
  nullable?: Nullable;
  /**
   * Group models under a foldable divider per provider. Pass
   * `!settings.hide_provider_grouping` to honour the admin setting. A
   * single provider always renders flat.
   */
  grouped?: boolean;
  /**
   * A first row, "Global Default", that stands for null, for pickers
   * where nothing chosen falls back to the workspace default. The row is
   * what null shows as, so the select never reads as empty and re-picking
   * it is a no-op; picking a model then the row emits null. Needs
   * `nullable`.
   */
  globalDefault?: Nullable extends true ? GlobalDefaultRow : never;
  disabled?: boolean;
  /**
   * Error chrome, e.g. while the models failed to load. Left undefined, the
   * select flags a value outside its options itself; false turns that off.
   */
  isError?: boolean;
  placeholder?: InputSingleSelectProps["placeholder"];
  /** Pages a truncated listing in: the end of the list loads more models,
   *  and a search no loaded model matches asks the server. */
  modelPaging?: ModelPaging;
  /** Where the list portals to; inside a modal, pass the modal content. */
  container?: InputSingleSelectProps["container"];
  /** The select input's id, so a `<label htmlFor>` (`withLabel="<id>"`) opens it. */
  id?: string;
  /**
   * Decision models in their own section above `providers`, for a setting
   * that takes either kind. A model can be in both lists; each copy is its
   * own row with its own callback.
   */
  decisionSection?: DecisionSection;
  /**
   * The row for `value` while the listing has not loaded that model, e.g. a
   * saved choice past the first page, so the select shows its name instead
   * of an invalid value. Ignored once the model loads.
   */
  selectedFallback?: SelectOption;
}

/**
 * A form select over model configurations, the plain counterpart of the
 * chat `ModelSelector`: an `InputSingleSelect` with a search field,
 * providers as foldable dividers and each model a row with its icon. No
 * per-model settings, and nothing chosen shows the placeholder rather than
 * a fallback.
 */
export default function SimpleModelSelector<Nullable extends boolean = false>({
  providers,
  value,
  onChange,
  nullable,
  grouped = true,
  includeDecisionOnly = false,
  globalDefault,
  disabled,
  isError,
  placeholder,
  modelPaging,
  container,
  id,
  decisionSection,
  selectedFallback,
}: SimpleModelSelectorProps<Nullable>) {
  const t = useTranslations("common.modelSelectors");
  const providerNames = useProviderNames();
  const decisionTitle = decisionSection?.title;
  const decisionProviders = decisionSection?.providers;
  const decisionRows = useMemo(
    (): SelectOption[] =>
      decisionProviders
        ? buildModelSelectOptions(decisionProviders, {
            grouped: false,
            providerNames,
            includeDecisionOnly: true,
          }).flatMap((option): SelectOption[] =>
            "options" in option
              ? []
              : [{ ...option, value: DECISION_SELECT_PREFIX + option.value }]
          )
        : [],
    [decisionProviders, providerNames]
  );
  // Under a decision section, a lone provider keeps its header so its rows
  // are not read as part of that section.
  const hasDecisionRows = decisionRows.length > 0;
  const models = useMemo(
    () =>
      buildModelSelectOptions(providers, {
        grouped,
        providerNames,
        includeDecisionOnly,
        labelSingleGroup: hasDecisionRows,
      }),
    [providers, grouped, providerNames, includeDecisionOnly, hasDecisionRows]
  );
  const fallbackRow =
    selectedFallback?.value === toSelectValue(value) &&
    !hasOptionValue(models, selectedFallback.value)
      ? selectedFallback
      : undefined;
  const options = useMemo((): SelectOptions => {
    if (!globalDefault && decisionRows.length === 0 && !fallbackRow) {
      return models;
    }
    // Loose model rows go under an untitled divider, so a line always
    // separates them from the rows above.
    const looseModels = models.filter(
      (option): option is SelectOption => !("options" in option)
    );
    return [
      ...(globalDefault
        ? [
            {
              value: GLOBAL_DEFAULT_SELECT_VALUE,
              title: globalDefault.label ?? t("globalDefault.label"),
              description: globalDefault.description ?? undefined,
              icon: getModelIcon("", ""),
            },
          ]
        : []),
      ...(fallbackRow ? [fallbackRow] : []),
      ...(decisionTitle && decisionRows.length > 0
        ? [{ title: decisionTitle, options: decisionRows }]
        : []),
      ...(looseModels.length === models.length
        ? [{ options: looseModels }]
        : models),
    ];
  }, [models, globalDefault, t, decisionTitle, decisionRows, fallbackRow]);

  // Server search only when nothing loaded matches. The query is remembered
  // so a merged page, which changes `modelPaging`, does not re-run it.
  const [query, setQuery] = useState("");
  const trimmedQuery = query.trim();
  const currentQueryRef = useRef("");
  const lastServerSearchRef = useRef("");
  useEffect(() => {
    currentQueryRef.current = trimmedQuery;
    if (trimmedQuery === "") {
      // A cleared or closed search forgets its server query, so the next
      // one runs even after a listing refresh dropped the merged matches.
      lastServerSearchRef.current = "";
      return;
    }
    // Only the paged models count: the decision section is fully loaded, so
    // its match must not hide a language model that is not loaded yet.
    if (!modelPaging?.hasMore || hasLoadedMatch(models, trimmedQuery)) return;
    if (lastServerSearchRef.current === trimmedQuery) return;
    const handle = setTimeout(() => {
      modelPaging
        .search(trimmedQuery)
        .then((searched) => {
          // A search that lands after its query was cleared is not remembered.
          if (searched && currentQueryRef.current === trimmedQuery) {
            lastServerSearchRef.current = trimmedQuery;
          }
        })
        .catch(console.error);
    }, SERVER_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [modelPaging, trimmedQuery, models]);

  // Which provider each row belongs to, so scrolling pages the providers
  // whose rows are on show rather than one hidden behind a folded group.
  const providerIdByValue = useMemo(() => {
    const byValue = new Map<string, number>();
    for (const provider of providers) {
      for (const mc of provider.model_configurations) {
        if (mc.id != null) byValue.set(String(mc.id), provider.id);
      }
    }
    return byValue;
  }, [providers]);

  // The end of the list pages the next window: of the current server
  // search's matches while searching, of a shown truncated provider otherwise.
  const loadNextWindow = useCallback(
    (shown: SelectOption[]) => {
      if (!modelPaging || modelPaging.isLoading) return;
      if (trimmedQuery !== "") {
        if (
          lastServerSearchRef.current === trimmedQuery &&
          modelPaging.searchHasMore
        ) {
          modelPaging.loadMoreSearch().catch(console.error);
        }
        return;
      }
      if (!modelPaging.hasMore) return;
      const shownProviderIds = [
        ...new Set(
          shown.flatMap((option) => providerIdByValue.get(option.value) ?? [])
        ),
      ];
      // A caller's filter can hide every loaded model of a provider that has
      // more pages, so with no shown provider left to page, page any.
      modelPaging
        .loadMore(shownProviderIds)
        .then((loaded) => (loaded ? undefined : modelPaging.loadMore()))
        .catch(console.error);
    },
    [modelPaging, trimmedQuery, providerIdByValue]
  );

  const selectValue =
    decisionSection?.selected && value !== null
      ? DECISION_SELECT_PREFIX + value
      : toSelectValue(value);

  // The Global Default row is what null shows as; otherwise a non-nullable
  // field's own value is its floor. Either way a re-pick is a no-op.
  const defaultOption = globalDefault
    ? GLOBAL_DEFAULT_SELECT_VALUE
    : nullable || value === null
      ? undefined
      : selectValue;

  return (
    <InputSingleSelect
      // Provider lists run long: the list always carries a search field.
      search
      value={selectValue}
      defaultOption={defaultOption}
      disabled={disabled}
      isError={isError}
      onValueChange={(next) => {
        if (decisionSection && next.startsWith(DECISION_SELECT_PREFIX)) {
          const decisionId = fromSelectValue(
            next.slice(DECISION_SELECT_PREFIX.length)
          );
          if (decisionId !== null) decisionSection.onChange(decisionId);
          return;
        }
        const id = fromSelectValue(next);
        // The Global Default row stands for null, so picking it while
        // nothing is chosen changes nothing; the family cannot tell, since
        // the select's own value is empty then.
        if (id === null && value === null) return;
        // SAFETY: a non-nullable select never emits an empty value, since
        // its own value is the default option.
        onChange(id as EmittedModelConfigurationId<Nullable>);
      }}
      placeholder={placeholder ?? t("placeholder")}
      options={options}
      onSearchChange={modelPaging ? setQuery : undefined}
      onReachEnd={modelPaging ? loadNextWindow : undefined}
      container={container}
      id={id}
    />
  );
}
