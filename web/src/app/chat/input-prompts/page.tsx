import InputPrompts from "@/app/chat/input-prompts/InputPrompts";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";
import { AppPageLayout } from "@/layouts/app-pages";

export default async function InputPromptsPage() {
  const headerData = await fetchHeaderDataSS();

  return (
    <AppPageLayout
      {...headerData}
      className="w-full px-32 py-16 mx-auto container"
    >
      <InputPrompts />
    </AppPageLayout>
  );
}
