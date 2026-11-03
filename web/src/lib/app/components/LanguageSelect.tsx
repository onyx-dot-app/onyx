"use client";

import { InputSingleSelect } from "@opal/components";
import { useTranslations } from "next-intl";
import {
  DEFAULT_LOCALE,
  LOCALE_ENDONYMS,
  LOCALE_OPTIONS,
  isSupportedLocale,
  type Locale,
} from "@/i18n/config";

/** The select value of the Global Default row, which stands for no override. */
const GLOBAL_DEFAULT_LANGUAGE_VALUE = "global-default";

interface WorkspaceLanguageSelectProps {
  value: Locale;
  onChange: (language: Locale) => void;
  globalDefault?: undefined;
  disabled?: boolean;
}

interface OverrideLanguageSelectProps {
  /** The override; null follows the workspace default. */
  value: Locale | null;
  onChange: (language: Locale | null) => void;
  /** The workspace default, shown under the Global Default row. */
  globalDefault: Locale;
  disabled?: boolean;
}

export type LanguageSelectProps =
  | WorkspaceLanguageSelectProps
  | OverrideLanguageSelectProps;

/**
 * UI language picker, listing each supported locale by its endonym. With
 * `globalDefault` it picks an override: a Global Default row, above a divider,
 * stands for null.
 */
export function LanguageSelect(props: LanguageSelectProps) {
  const t = useTranslations("common");
  const placeholder = t("inputSelect.placeholder.fallback");

  if (props.globalDefault === undefined) {
    const { value, onChange, disabled } = props;
    return (
      <InputSingleSelect
        value={value}
        onValueChange={(next) => {
          if (isSupportedLocale(next)) onChange(next);
        }}
        defaultOption={DEFAULT_LOCALE}
        placeholder={placeholder}
        options={LOCALE_OPTIONS}
        disabled={disabled}
      />
    );
  }

  const { value, onChange, globalDefault, disabled } = props;
  return (
    <InputSingleSelect
      value={value ?? ""}
      onValueChange={(next) => {
        if (isSupportedLocale(next)) {
          onChange(next);
        } else if (value !== null) {
          onChange(null);
        }
      }}
      defaultOption={GLOBAL_DEFAULT_LANGUAGE_VALUE}
      placeholder={placeholder}
      options={[
        {
          value: GLOBAL_DEFAULT_LANGUAGE_VALUE,
          title: t("languageSelect.globalDefault.label"),
          description: LOCALE_ENDONYMS[globalDefault],
        },
        { options: LOCALE_OPTIONS },
      ]}
      disabled={disabled}
    />
  );
}
