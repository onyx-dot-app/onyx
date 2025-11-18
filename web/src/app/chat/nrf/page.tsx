import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { cookies } from "next/headers";
import NRFPage from "./NRFPage";
import { NRFPreferencesProvider } from "../../../components/context/NRFPreferencesContext";
import { fetchSettingsSS } from "@/components/settings/lib";
import AppPage from "@/refresh-components/layouts/AppPage";

export default async function Page() {
  noStore();
  const requestCookies = await cookies();
  const settings = await fetchSettingsSS();

  const appPageProps = {
    settings,
    chatSession: null,
  };

  return (
    <AppPage {...appPageProps}>
      <InstantSSRAutoRefresh />
      <NRFPreferencesProvider>
        <NRFPage requestCookies={requestCookies} />
      </NRFPreferencesProvider>
    </AppPage>
  );
}
