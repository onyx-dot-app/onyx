import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "@/app/app/nrf/NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";

export default async function Page() {
  noStore();

  return (
    <div className="h-full w-full flex flex-col overflow-hidden">
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage isSidePanel />
      </NRFPreferencesProvider>
    </div>
  );
}
