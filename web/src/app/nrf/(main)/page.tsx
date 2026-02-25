import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "@/app/nrf/NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import NRFChrome from "../NRFChrome";

/**
 * NRF (New Tab Page) Route - No Auth Required
 *
 * This route is placed outside /app/app/ to bypass the authentication
 * requirement in /app/app/layout.tsx. The NRFPage component handles
 * unauthenticated users gracefully by showing a login modal instead of
 * redirecting, which is better UX for the Chrome extension.
 *
 * Instead of AppLayouts.Root (which pulls in heavy Header state management),
 * we use NRFChrome — a lightweight overlay that renders only the search/chat
 * mode toggle and footer, floating transparently over NRFPage's background.
 */
export default async function Page() {
  noStore();

  return (
    <div className="relative w-full h-full">
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage />
      </NRFPreferencesProvider>
      <NRFChrome />
    </div>
  );
}
