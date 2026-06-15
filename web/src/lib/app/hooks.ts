import { useSettingsContext } from "@/providers/SettingsProvider";
import { APP_SLOGAN } from "@/lib/constants";
import { ensureHrefProtocol } from "@/lib/utils";

export function useCustomFooterContent(): string {
  const settings = useSettingsContext();
  const raw =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${settings?.webVersion || "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`;
  return raw.replace(
    /\]\(([^)]+)\)/g,
    (_, url) => `](${ensureHrefProtocol(url) ?? url})`
  );
}
