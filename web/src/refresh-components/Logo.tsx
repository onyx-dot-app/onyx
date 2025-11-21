import { useMemo } from "react";
import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

export const FOLDED_SIZE = 24;
const UNFOLDED_SIZE = 88;

export interface LogoProps {
  folded?: boolean;
  className?: string;
}

export default function Logo({ folded, className }: LogoProps) {
  const settings = useSettingsContext();

  const isCustom = true;
  const logo = useMemo(
    () =>
      isCustom ? (
        <img
          src="/web/public/logo.png"
          alt="Logo"
          style={{
            objectFit: "contain",
            height: FOLDED_SIZE,
            width: FOLDED_SIZE,
          }}
          className={cn("flex-shrink-0", className)}
        />
      ) : (
        <img
          src="/web/public/logo.png"
          alt="Logo"
          style={{
            objectFit: "contain",
            height: FOLDED_SIZE,
            width: FOLDED_SIZE,
          }}
          className={cn("flex-shrink-0", className)}
        />
      ),
    [className, settings.enterpriseSettings?.use_custom_logo]
  );

  return isCustom ? (
    <div className="flex flex-col">
      <div className="flex flex-row items-center gap-2">
        {logo}
        <Text
          headingH3
          className={cn("line-clamp-1 truncate", folded && "invisible")}
          nowrap
        >
          Dom Engin.
        </Text>
      </div>
    </div>
  ) : folded ? (
    <OnyxIcon size={FOLDED_SIZE} className={cn("flex-shrink-0", className)} />
  ) : (
    <OnyxLogoTypeIcon size={UNFOLDED_SIZE} className={className} />
  );
}
