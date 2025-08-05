import { useMemo, useContext } from "react";
import { useUser } from "@/components/user/UserProvider";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { UserRole } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";

export function useAllowedConnectors(allSources: SourceMetadata[]) {
  const { user } = useUser();
  const settings = useContext(SettingsContext);

  const allowedSources = useMemo(() => {
    // If user is not a curator, show all sources
    if (
      !user ||
      ![UserRole.CURATOR, UserRole.GLOBAL_CURATOR].includes(user.role)
    ) {
      return allSources;
    }

    // If no curator restrictions are set, show all sources
    const allowedList = settings?.settings?.curator_allowed_connector_list;
    if (!allowedList) {
      return allSources;
    }

    // Parse the allowed connector list and filter sources
    const allowedConnectors = allowedList
      .split(",")
      .map((type) => type.trim().toLowerCase().replace("_", ""))
      .filter((type) => type);

    return allSources.filter((source) => {
      const sourceType = source.internalName.toLowerCase().replace("_", "");
      return allowedConnectors.includes(sourceType);
    });
  }, [allSources, user, settings]);

  return allowedSources;
}
