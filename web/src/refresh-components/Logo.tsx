import { useMemo } from "react";
import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";
import { EEAIcon, EEALogoTypeIcon  } from "../components/EEA_Logo";

import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

export const FOLDED_SIZE = 24;
const UNFOLDED_SIZE = 80;

export interface LogoProps {
  folded?: boolean;
  className?: string;
}

export default function Logo({ folded, className }: LogoProps) {
  const settings = useSettingsContext();

  const logo = useMemo(
    () =>
      settings.enterpriseSettings?.use_custom_logo ? (
        <img
          src="/api/enterprise-settings/logo"
          alt="Logo"
          style={{
            objectFit: "contain",
            height: FOLDED_SIZE,
            width: FOLDED_SIZE,
          }}
          className={cn("flex-shrink-0", className)}
        />
      ) : (
        <OnyxIcon
          size={FOLDED_SIZE}
          className={cn("flex-shrink-0", className)}
        />
      ),
    [className, settings.enterpriseSettings?.use_custom_logo]
  );

  return settings.enterpriseSettings?.application_name ? (
    <div className="flex flex-col">
      <div className="flex flex-row items-center gap-2">
        {logo}
        <Text
          headingH3
          className={cn("line-clamp-1 truncate", folded && "invisible")}
          nowrap
        >
          {settings.enterpriseSettings?.application_name}
        </Text>
      </div>
      {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
        <Text
          secondaryBody
          text03
          className={cn(
            "ml-[33px] line-clamp-1 truncate",
            folded && "invisible"
          )}
          nowrap
        >
          Powered by Onyx
        </Text>
      )}
    </div>
  ) : folded ? (
    <OnyxIcon size={FOLDED_SIZE} className={cn("flex-shrink-0", className)} />
  ) : (
    <EEALogoTypeIcon size={UNFOLDED_SIZE} className={className} />
  );
}
