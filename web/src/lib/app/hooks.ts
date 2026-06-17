import { useEnterpriseSettings, useSettings } from "@/lib/settings/hooks";
import { APP_SLOGAN } from "@/lib/constants";

export function useCustomFooterContent(): string {
  const { enterpriseSettings } = useEnterpriseSettings();
  const { settings } = useSettings();
  return (
    enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${settings.version ?? "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`
  );
}
