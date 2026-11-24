import { useTranslations } from "next-intl";
import { CompletedHeader } from "@/lib/timeline/components/headers/CompletedHeader";
import { STEP_ICONS } from "@/lib/timeline/icons";

/** The stopped run's title, with the stopped step's icon. */
export function StoppedHeader() {
  const t = useTranslations("chat.messages.timeline");
  return (
    <CompletedHeader
      text={t("interruptedThinking.label")}
      icon={STEP_ICONS.stopped}
    />
  );
}
