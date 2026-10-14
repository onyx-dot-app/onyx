"use client";

import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import { DEFAULT_LOGO_SIZE_PX } from "@/lib/constants";
import { cn } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { SvgOnyxLogo, SvgOnyxLogoTyped } from "@opal/logos";
import { IconProps } from "@opal/types";

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
      {/* eslint-disable-next-line @next/next/no-img-element */}
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
      <SvgOnyxLogoTyped size={resolvedSize} className={className} />
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
              <Truncated headingH3>{applicationName}</Truncated>
            )}
            {/* Wait for settings so a hidden tagline never flashes. */}
            {!isLoading && !hide_onyx_branding && (
              <Text
                secondaryBody
                text03
                className={"line-clamp-1 truncate"}
                nowrap
              >
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
    <SvgOnyxLogoTyped size={resolvedSize} className={className} />
  );
}
