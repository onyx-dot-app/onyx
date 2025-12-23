import AgentsPage from "@/refresh-pages/AgentsPage";
import AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  return (
    <AppLayouts.Root>
      <AgentsPage />
    </AppLayouts.Root>
  );
}
