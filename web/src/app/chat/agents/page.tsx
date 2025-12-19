import AgentsNavigationPage from "@/refresh-pages/AgentsNavigationPage";
import { AppPageLayout } from "@/layouts/pages";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";

export default async function Page() {
  const headerData = await fetchHeaderDataSS();

  return (
    <AppPageLayout {...headerData}>
      <AgentsNavigationPage />
    </AppPageLayout>
  );
}
