import AgentEditorPage from "@/refresh-pages/AgentEditorPage";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  return (
    <AppLayouts.Root>
      <AgentEditorPage />
    </AppLayouts.Root>
  );
}
