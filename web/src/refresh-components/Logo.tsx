import { useMemo } from "react";
import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

const FOLDED_SIZE = 24;

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

  if (folded) return logo;

  return settings.enterpriseSettings?.application_name ? (
    <div className="flex flex-col">
      <div className="flex flex-row items-center gap-spacing-interline">
        {logo}
        <Text headingH3 className="break-all line-clamp-2">
          {settings.enterpriseSettings?.application_name}
        </Text>
      </div>
      {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
        <Text secondaryBody text03 className="ml-[33px]">
          Powered by Onyx
        </Text>
      )}
    </div>
  ) : (
    <OnyxLogoTypeIcon size={88} className={className} />
  );
}
