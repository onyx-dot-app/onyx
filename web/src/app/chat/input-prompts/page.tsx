import InputPrompts from "@/app/chat/input-prompts/InputPrompts";
import { fetchHeaderDataSS } from "@/lib/headers/fetchHeaderDataSS";
import * as Layouts from "@/refresh-components/layouts/layouts";

export default async function InputPromptsPage() {
  const headerData = await fetchHeaderDataSS();

  return (
    <Layouts.AppPage
      {...headerData}
      className="w-full px-32 py-16 mx-auto container"
    >
      <InputPrompts />
    </Layouts.AppPage>
  );
}
