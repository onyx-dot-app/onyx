import AgentsPage from "@/refresh-pages/AgentsPage";
import { fetchSettingsSS } from "@/components/settings/lib";
import AppPage from "@/refresh-components/layouts/AppPage";

export default async function Page() {
  const settings = await fetchSettingsSS();

  const appPageProps = {
    chatSession: null,
    settings,
  };

  return (
    <AppPage {...appPageProps}>
      <AgentsPage />
    </AppPage>
  );
}
