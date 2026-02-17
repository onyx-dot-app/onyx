import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "@/app/app/nrf/NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import { ProjectsProvider } from "@/providers/ProjectsContext";

/**
 * NRF Side Panel Route - No Auth Required
 *
 * This route is placed outside /app/app/ to bypass the authentication
 * requirement in /app/app/layout.tsx. The NRFPage component handles
 * unauthenticated users gracefully by showing a login modal instead of
 * redirecting, which is better UX for the Chrome extension.
 */
export default async function Page() {
  noStore();

  return (
    <ProjectsProvider>
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage isSidePanel />
      </NRFPreferencesProvider>
    </ProjectsProvider>
  );
}
