import AgentsPage from "@/refresh-pages/AgentsPage";
import { AppPageLayout } from "@/layouts/app-pages";

export default async function Page() {
  return (
    <AppPageLayout>
      <AgentsPage />
    </AppPageLayout>
  );
}
