"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { InputSingleSelect } from "@opal/components";
import {
  buildModelSelectOptions,
  fromSelectValue,
  toSelectValue,
} from "@/lib/languageModels/options";
import type { ModelOptionProvider } from "@/lib/languageModels/types";

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
}: SimpleModelSelectorProps<Nullable>) {
  const t = useTranslations("common.modelSelectors");
  const options = useMemo(
    () => buildModelSelectOptions(providers, { grouped }),
    [providers, grouped]
  );

  return (
    <InputSingleSelect
      // Provider lists run long: the list always carries a search field.
      search
      value={toSelectValue(value)}
      // A non-nullable field's own value is its floor: a re-pick is a no-op.
      defaultOption={nullable || value === null ? undefined : String(value)}
      onValueChange={(next) => {
        const id = fromSelectValue(next);
        // SAFETY: a non-nullable select never emits an empty value, since
        // its own value is the default option.
        onChange(id as EmittedModelConfigurationId<Nullable>);
      }}
      placeholder={t("placeholder")}
      options={options}
    />
  );
}
