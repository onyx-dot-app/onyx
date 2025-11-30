import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

export function useApplicationName() {
  const settings = useSettingsContext();
  return (
    settings.enterpriseSettings?.application_name ?? DEFAULT_APPLICATION_NAME
  );
}
