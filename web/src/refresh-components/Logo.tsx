"use client";

import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import {
  LOGO_FOLDED_SIZE_PX,
  LOGO_UNFOLDED_SIZE_PX,
  NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED,
} from "@/lib/constants";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { useMemo } from "react";

export interface LogoProps {
  folded?: boolean;
  size?: number;
  className?: string;
}

export default function Logo({ folded, size, className }: LogoProps) {
  const foldedSize = size ?? LOGO_FOLDED_SIZE_PX;
  const unfoldedSize = size ?? LOGO_UNFOLDED_SIZE_PX;
  const settings = useSettingsContext();
  const logoDisplayStyle = settings.enterpriseSettings?.logo_display_style;

  const logo = useMemo(
    () =>
      settings.enterpriseSettings?.use_custom_logo ? (
        <img
          src="/api/enterprise-settings/logo"
          alt="Logo"
          style={{
            objectFit: "contain",
            height: foldedSize,
            width: foldedSize,
          }}
          className={cn("flex-shrink-0", className)}
        />
      ) : (
        <OnyxIcon
          size={foldedSize}
          className={cn("flex-shrink-0", className)}
        />
      ),
    [className, settings.enterpriseSettings?.use_custom_logo]
  );

  // Handle "none" display style
  if (logoDisplayStyle === "none") {
    return null;
  }

  // Handle "logo_only" display style
  if (logoDisplayStyle === "logo_only") {
    return logo;
  }

  // Handle "logo_and_name" or default behavior
  return settings.enterpriseSettings?.application_name ? (
    <div className="flex flex-col">
      <div className="flex flex-row items-center gap-2 min-w-0">
        {logo}
        <div className="flex-1 min-w-0">
          <Truncated headingH3 className={cn(folded && "invisible")}>
            {settings.enterpriseSettings?.application_name}
          </Truncated>
        </div>
      </div>
      {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
        <Text
          secondaryBody
          text03
          className={cn("ml-[33px] line-clamp-1 truncate", folded && "hidden")}
          nowrap
        >
          Powered by Onyx
        </Text>
      )}
    </div>
  ) : folded ? (
    <OnyxIcon size={foldedSize} className={cn("flex-shrink-0", className)} />
  ) : (
    <OnyxLogoTypeIcon size={unfoldedSize} className={className} />
  );
}
