"use client";

import { InputSingleSelect, OverflowText, Text } from "@opal/components";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import { DEFAULT_LOGO_SIZE_PX } from "@/lib/constants";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import { SvgOnyxLogo, SvgOnyxLogoWordmark, SvgOnyxWordmark } from "@opal/logos";
import { IconProps } from "@opal/types";
import {
  DEFAULT_LOCALE,
  LOCALE_ENDONYMS,
  LOCALE_OPTIONS,
  isSupportedLocale,
  type Locale,
} from "@/i18n/config";

export interface LogoProps extends IconProps {
  // Always render the real Onyx mark, ignoring the enterprise custom logo.
  // Used by Onyx-branded surfaces like Craft.
  onyxBranded?: boolean;
}

/**
 * The app mark alone: the uploaded custom logo when one is set, the Onyx
 * mark otherwise. Shaped like an Opal icon, so it fits any `icon` slot and
 * honours the size or style the slot passes.
 */
export function Logo({ size, className, style, onyxBranded }: LogoProps) {
  const t = useTranslations("common");
  const resolvedSize = size ?? DEFAULT_LOGO_SIZE_PX;
  const { logoUrl } = useSettings();

  if (onyxBranded || !logoUrl) {
    return (
      <SvgOnyxLogo
        size={resolvedSize}
        className={cn("shrink-0", className)}
        style={style}
      />
    );
  }

  return (
    <div
      className={cn(
        "aspect-square rounded-full overflow-hidden relative shrink-0",
        className
      )}
      style={{ height: resolvedSize, ...style }}
    >
      <img
        alt={t("logo.image.alt")}
        src={logoUrl}
        className="object-cover object-center w-full h-full"
      />
    </div>
  );
}

export interface FoldableLogoProps extends LogoProps {
  folded?: boolean;
}

/**
 * The sidebar's brand block: the mark, and when unfolded the application
 * name and the "powered by" line beside it, per the enterprise display style.
 */
export function FoldableLogo({
  folded,
  size,
  className,
  onyxBranded,
}: FoldableLogoProps) {
  const t = useTranslations("common");
  const resolvedSize = size ?? DEFAULT_LOGO_SIZE_PX;
  const { enterprise, hide_onyx_branding, isLoading } = useSettings();
  const logoDisplayStyle = enterprise?.logo_display_style;
  const applicationName = enterprise?.application_name;

  if (onyxBranded) {
    return folded ? (
      <Logo onyxBranded size={resolvedSize} className={className} />
    ) : (
      <SvgOnyxLogoWordmark size={resolvedSize} className={className} />
    );
  }

  const logo = <Logo size={resolvedSize} className={className} />;

  const renderNameAndPoweredBy = (opts: {
    includeLogo: boolean;
    includeName: boolean;
  }) => {
    return (
      <div className="flex min-w-0 gap-2">
        {opts.includeLogo && logo}
        {!folded && (
          /* H3 text is 4px larger (28px) than the Logo icon (24px), so negative margin hack. */
          <div className="flex flex-1 flex-col -mt-0.5">
            {opts.includeName && (
              <OverflowText
                as="p"
                textPosition="text-start"
                font="heading-h3"
                color="text-05"
              >
                {applicationName ?? ""}
              </OverflowText>
            )}
            {/* Wait for settings so a hidden tagline never flashes. */}
            {!isLoading && !hide_onyx_branding && (
              <Text font="secondary-body" color="text-03" maxLines={1}>
                {t("logo.poweredBy.label")}
              </Text>
            )}
          </div>
        )}
      </div>
    );
  };

  // Handle "logo_only" display style
  if (logoDisplayStyle === "logo_only") {
    return renderNameAndPoweredBy({ includeLogo: true, includeName: false });
  }

  // Handle "name_only" display style
  if (logoDisplayStyle === "name_only") {
    return renderNameAndPoweredBy({ includeLogo: false, includeName: true });
  }

  // Handle "logo_and_name" or default behavior
  return applicationName ? (
    renderNameAndPoweredBy({ includeLogo: true, includeName: true })
  ) : folded ? (
    <Logo size={resolvedSize} className={className} />
  ) : (
    <SvgOnyxLogoWordmark size={resolvedSize} className={className} />
  );
}

/**
 * The sidebar's logo mark: the workspace's custom logo, or the Onyx mark.
 * Renders nothing when the workspace shows its name only.
 */
export function SidebarLogoMark({ size }: { size: number }) {
  const { enterprise } = useSettings();
  if (enterprise?.logo_display_style === "name_only") return null;
  return <Logo size={size} />;
}

/**
 * The sidebar's wordmark, beside the mark: the workspace's name with the
 * "Powered by" line, or the Onyx wordmark when no custom name is set.
 */
export function SidebarWordmark({ size }: { size: number }) {
  const t = useTranslations("common");
  const { enterprise, hide_onyx_branding, isLoading } = useSettings();
  const logoDisplayStyle = enterprise?.logo_display_style;
  const applicationName = enterprise?.application_name;

  const customStyle =
    logoDisplayStyle === "logo_only" || logoDisplayStyle === "name_only";
  if (!customStyle && !applicationName) {
    return <SvgOnyxWordmark size={size} />;
  }

  return (
    /* H3 text is 4px larger (28px) than the Logo icon (24px), so negative margin hack. */
    <Section
      flexDirection="column"
      alignItems="start"
      justifyContent="start"
      gap={0}
      height="fit"
      className="min-w-0 flex-1 -mt-0.5"
    >
      {logoDisplayStyle !== "logo_only" && (
        <OverflowText
          as="p"
          textPosition="text-start"
          font="heading-h3"
          color="text-05"
        >
          {applicationName ?? ""}
        </OverflowText>
      )}
      {/* Wait for settings so a hidden tagline never flashes. */}
      {!isLoading && !hide_onyx_branding && (
        <Text font="secondary-body" color="text-03" maxLines={1}>
          {t("logo.poweredBy.label")}
        </Text>
      )}
    </Section>
  );
}

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
