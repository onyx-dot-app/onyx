import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "./NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  noStore();

  return (
    <AppLayouts.Root>
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage />
      </NRFPreferencesProvider>
    </AppLayouts.Root>
  );
}
