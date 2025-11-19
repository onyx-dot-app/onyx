import AgentsPage from "@/refresh-pages/AgentsPage";
import * as Layouts from "@/refresh-components/layouts/Layouts";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";

export default async function Page() {
  const headerData = await fetchHeaderDataSS();

  return (
    <Layouts.AppPage {...headerData}>
      <AgentsPage />
    </Layouts.AppPage>
  );
}
