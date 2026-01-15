import InputPrompts from "@/app/chat/input-prompts/InputPrompts";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function InputPromptsPage() {
  return (
    <AppLayouts.Root>
      <InputPrompts />
    </AppLayouts.Root>
  );
}
