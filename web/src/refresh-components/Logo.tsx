import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";
import Text from "@/refresh-components/texts/Text";

export interface LogoProps {
  folded?: boolean;
  className?: string;
}

export default function Logo({ folded, className }: LogoProps) {
  const settings = useSettingsContext();

  const logo = <OnyxIcon size={24} className={className} />;

  if (folded) return logo;

  return settings.enterpriseSettings?.application_name ? (
    <div className="flex flex-col">
      <div className="flex flex-row items-center gap-spacing-interline">
        {logo}
        <Text headingH2>{settings.enterpriseSettings?.application_name}</Text>
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
