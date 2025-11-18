import { fetchSettingsSS } from "@/components/settings/lib";
import InputPrompts from "@/app/chat/input-prompts/InputPrompts";
import AppPage from "@/refresh-components/layouts/AppPage";

export default async function InputPromptsPage() {
  const settings = await fetchSettingsSS();

  const appPageProps = {
    chatSession: null,
    settings,
  };

  return (
    <AppPage {...appPageProps} className="w-full px-32 py-16 mx-auto container">
      <InputPrompts />
    </AppPage>
  );
}
