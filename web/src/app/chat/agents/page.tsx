import AgentsPage from "@/refresh-pages/AgentsPage";
import AppPageLayout from "@/layouts/AppPageLayout";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";

export default async function Page() {
  const headerData = await fetchHeaderDataSS();

  return (
    <AppPageLayout {...headerData}>
      <AgentsPage />
    </AppPageLayout>
  );
}
