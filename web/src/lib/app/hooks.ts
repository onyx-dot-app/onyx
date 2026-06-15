import { useSettingsContext } from "@/providers/SettingsProvider";
import { APP_SLOGAN } from "@/lib/constants";

export function useCustomFooterContent(): string {
  const settings = useSettingsContext();
  return (
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${settings?.webVersion || "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`
  );
}
