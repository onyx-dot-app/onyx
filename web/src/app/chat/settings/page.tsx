import * as AppLayouts from "@/layouts/app-layouts";
import SettingsPage from "@/refresh-pages/SettingsPage";

export default async function Page() {
  return (
    <AppLayouts.Root>
      <SettingsPage />
    </AppLayouts.Root>
  );
}
