import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import NRFPage from "./NRFPage";
import { NRFPreferencesProvider } from "../../../components/context/NRFPreferencesContext";
import AppPageLayout from "@/layouts/AppPageLayout";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";
import { PerformancePolyfill } from "@/components/PerformancePolyfill";

export default async function Page() {
  noStore();
  const headerData = await fetchHeaderDataSS();

  return (
    <AppPageLayout {...headerData} className="h-full w-full" hideShareChat>
      <PerformancePolyfill />
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage />
      </NRFPreferencesProvider>
    </AppPageLayout>
  );
}
