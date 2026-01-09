import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "@/app/chat/nrf/NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  noStore();

  return (
    <AppLayouts.Root>
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage isSidePanel />
      </NRFPreferencesProvider>
    </AppLayouts.Root>
  );
}
