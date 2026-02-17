import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "@/app/app/nrf/NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import { ProjectsProvider } from "@/providers/ProjectsContext";
import * as AppLayouts from "@/layouts/app-layouts";

/**
 * NRF (New Tab Page) Route - No Auth Required
 *
 * This route is placed outside /app/app/ to bypass the authentication requirement.
 * The NRFPage component handles unauthenticated users gracefully by showing a
 * login modal instead of redirecting, which is better UX for the Chrome extension.
 */
export default async function Page() {
  noStore();

  return (
    <ProjectsProvider>
      <AppLayouts.Root>
        <InstantSSRAutoRefresh />
        <NRFPreferencesProvider>
          <NRFPage />
        </NRFPreferencesProvider>
      </AppLayouts.Root>
    </ProjectsProvider>
  );
}
