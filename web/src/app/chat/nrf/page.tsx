import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { cookies } from "next/headers";
import NRFPage from "./NRFPage";
import { NRFPreferencesProvider } from "@/components/context/NRFPreferencesContext";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  noStore();
  const requestCookies = await cookies();

  return (
    <AppLayouts.Root>
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage />
      </NRFPreferencesProvider>
    </AppLayouts.Root>
  );
}
