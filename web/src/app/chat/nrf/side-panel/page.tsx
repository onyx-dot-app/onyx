import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "@/app/chat/nrf/NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import * as AppLayouts from "@/layouts/app-layouts";
import { NRFDisplayMode } from "@/app/chat/nrf/types";

export default async function Page() {
  noStore();

  return (
    <AppLayouts.Root>
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage displayMode={NRFDisplayMode.SIDE_PANEL} />
      </NRFPreferencesProvider>
    </AppLayouts.Root>
  );
}
