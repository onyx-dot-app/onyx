import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { cookies } from "next/headers";
import NRFPage from "./NRFPage";
import { NRFPreferencesProvider } from "../../../components/context/NRFPreferencesContext";
import * as Layouts from "@/refresh-components/layouts/layouts2";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";

export default async function Page() {
  noStore();
  const requestCookies = await cookies();
  const headerData = await fetchHeaderDataSS();

  return (
    <Layouts.AppPage {...headerData} className="h-full w-full">
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage requestCookies={requestCookies} />
      </NRFPreferencesProvider>
    </Layouts.AppPage>
  );
}
