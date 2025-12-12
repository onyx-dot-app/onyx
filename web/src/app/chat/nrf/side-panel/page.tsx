import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "../NRFPage";
import AppPageLayout from "@/layouts/AppPageLayout";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import { PerformancePolyfill } from "@/components/PerformancePolyfill";

export default async function Page() {
  noStore();
  const headerData = await fetchHeaderDataSS();

  return (
    <AppPageLayout {...headerData} className="h-full w-full" hideShareChat>
      <PerformancePolyfill />
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage isSidePanel />
      </NRFPreferencesProvider>
    </AppPageLayout>
  );
}
