import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import Text from "./texts/Text";

export interface LogoProps {
  folded?: boolean;
  className?: string;
}

export default function Logo({ folded, className }: LogoProps) {
  const settings = useSettingsContext();

  if (folded) return <OnyxIcon size={24} className={className} />;

  return settings.enterpriseSettings?.application_name ? (
    <div className="flex flex-row">
      <OnyxIcon size={24} />
      <Text headingH2>{settings.enterpriseSettings.application_name}</Text>
    </div>
  ) : (
    <OnyxLogoTypeIcon size={88} />
  );
}
