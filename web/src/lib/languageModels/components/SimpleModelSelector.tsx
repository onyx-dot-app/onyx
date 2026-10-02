"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { InputSingleSelect } from "@opal/components";
import type {
  SelectOption,
  SelectOptions,
} from "@opal/components/inputs/dropdowns/types";
import { optionMatchesSearch } from "@opal/components/inputs/dropdowns/shared";
import {
  buildModelSelectOptions,
  fromSelectValue,
  toSelectValue,
} from "@/lib/languageModels/options";
import { getModelIcon } from "@/lib/languageModels/utils";
import { useServerModelSearch } from "@/lib/languageModels/hooks";
import type {
  ModelOptionProvider,
  ModelPaging,
} from "@/lib/languageModels/types";

/** The select value of the Global Default row; `fromSelectValue` reads it as null. */
const GLOBAL_DEFAULT_SELECT_VALUE = "global-default";

/** True when the list's own filter would show at least one loaded row. */
function hasLoadedMatch(options: SelectOptions, query: string): boolean {
  const term = query.toLowerCase();
  return options.some((item) =>
    "options" in item
      ? (item.title?.toLowerCase().includes(term) ?? false) ||
        item.options.some((opt) => optionMatchesSearch(opt, term))
      : optionMatchesSearch(item, term)
  );
}

export interface GlobalDefaultRow {
  /** The model null resolves to, shown under the row's title. */
  description?: string | null;
}

/** What `onChange` emits: only a nullable selector can emit null. */
type EmittedModelConfigurationId<Nullable extends boolean> =
  Nullable extends true ? number | null : number;

export interface SimpleModelSelectorProps<Nullable extends boolean = false> {
  /**
   * The model configurations to offer, grouped by provider. Nothing is
   * filtered here: pass the list you want shown, trimmed with
   * `filterModelConfigurations` when needed.
   */
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
  /** Pages a truncated listing in: the end of the list loads more models,
   *  and a search no loaded model matches asks the server. */
  modelPaging?: ModelPaging;
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
  globalDefault,
  disabled,
  modelPaging,
}: SimpleModelSelectorProps<Nullable>) {
  const t = useTranslations("common.modelSelectors");
  const options = useMemo((): SelectOptions => {
    const models = buildModelSelectOptions(providers, { grouped });
    if (!globalDefault) return models;
    return [
      {
        value: GLOBAL_DEFAULT_SELECT_VALUE,
        title: t("globalDefault.label"),
        description: globalDefault.description ?? undefined,
        icon: getModelIcon("", ""),
      },
      ...models,
    ];
  }, [providers, grouped, globalDefault, t]);

  // Server search only when nothing loaded matches.
  const [query, setQuery] = useState("");
  const trimmedQuery = query.trim();
  const serverSearched = useServerModelSearch(
    modelPaging,
    trimmedQuery,
    (modelPaging?.hasMore ?? false) && !hasLoadedMatch(options, trimmedQuery)
  );

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
        if (serverSearched && modelPaging.searchHasMore) {
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
      modelPaging.loadMore(shownProviderIds).catch(console.error);
    },
    [modelPaging, trimmedQuery, serverSearched, providerIdByValue]
  );

  // The Global Default row is what null shows as; otherwise a non-nullable
  // field's own value is its floor. Either way a re-pick is a no-op.
  const defaultOption = globalDefault
    ? GLOBAL_DEFAULT_SELECT_VALUE
    : nullable || value === null
      ? undefined
      : String(value);

  return (
    <InputSingleSelect
      // Provider lists run long: the list always carries a search field.
      search
      value={toSelectValue(value)}
      defaultOption={defaultOption}
      disabled={disabled}
      onValueChange={(next) => {
        const id = fromSelectValue(next);
        // The Global Default row stands for null, so picking it while
        // nothing is chosen changes nothing; the family cannot tell, since
        // the select's own value is empty then.
        if (id === null && value === null) return;
        // SAFETY: a non-nullable select never emits an empty value, since
        // its own value is the default option.
        onChange(id as EmittedModelConfigurationId<Nullable>);
      }}
      placeholder={t("placeholder")}
      options={options}
      onSearchChange={modelPaging ? setQuery : undefined}
      onReachEnd={modelPaging ? loadNextWindow : undefined}
    />
  );
}
