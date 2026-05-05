import AgentWizardPage from "@/refresh-pages/AgentWizardPage";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  return (
    <AppLayouts.Root>
      <AgentWizardPage />
    </AppLayouts.Root>
  );
}
