import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { cookies } from "next/headers";
import NRFPage from "./NRFPage";
import { NRFPreferencesProvider } from "../../../components/context/NRFPreferencesContext";

export default async function Page() {
  noStore();
  const requestCookies = await cookies();

  return (
    <div className="w-full h-full bg-black">
      <InstantSSRAutoRefresh />

      <NRFPreferencesProvider>
        <NRFPage requestCookies={requestCookies} />
      </NRFPreferencesProvider>
    </div>
  );
}
