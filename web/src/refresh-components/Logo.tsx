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

export interface LogoProps {
  folded?: boolean;
  size?: number;
  className?: string;
}

export default function Logo({ folded, size, className }: LogoProps) {
  const foldedSize = size ?? LOGO_FOLDED_SIZE_PX;
  const unfoldedSize = size ?? LOGO_UNFOLDED_SIZE_PX;
  const settings = useSettingsContext();

  return settings.enterpriseSettings?.application_name ? (
    <div className="flex flex-col">
      <div className="flex flex-row items-center gap-2">
        {settings.enterpriseSettings?.use_custom_logo ? (
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
        )}
        <Text
          headingH3
          className={cn("line-clamp-1 truncate", folded && "hidden")}
          nowrap
        >
          {settings.enterpriseSettings?.application_name}
        </Text>
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
