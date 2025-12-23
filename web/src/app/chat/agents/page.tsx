import AgentsPage from "@/refresh-pages/AgentsPage";
import { AppPageLayout } from "@/layouts/app-layouts";

export default async function Page() {
  return (
    <AppPageLayout>
      <AgentsPage />
    </AppPageLayout>
  );
}
