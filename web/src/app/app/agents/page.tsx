import AgentsNavigationPage from "@/refresh-pages/AgentsNavigationPage";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  return (
    <AppLayouts.Root>
      <AgentsNavigationPage />
    </AppLayouts.Root>
  );
}
