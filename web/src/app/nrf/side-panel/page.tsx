import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "@/app/nrf/NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";

/**
 * NRF Side Panel Route - No Auth Required
 *
 * Side panel variant — no NRFChrome overlay needed since the side panel
 * has its own header (logo + "Open in Onyx" button) and doesn't show
 * the mode toggle or footer.
 */
export default async function Page() {
  noStore();

  return (
    <>
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage isSidePanel />
      </NRFPreferencesProvider>
    </>
  );
}
