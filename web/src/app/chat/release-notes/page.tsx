import { AppPageLayout } from "@/layouts/app-pages";
import ReleaseNotesPage from "@/app/chat/release-notes/ReleaseNotesPage";

export default async function Page() {
  return (
    <AppPageLayout>
      <ReleaseNotesPage />
    </AppPageLayout>
  );
}
