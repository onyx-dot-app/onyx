import { useTranslations } from "next-intl";
import { Text } from "@opal/components";

/** The stopped run's title. */
export function StoppedHeader() {
  const t = useTranslations("chat.messages.timeline");
  return (
    <div className="flex-1 min-w-0 px-(--timeline-header-text-padding-x) py-(--timeline-header-text-padding-y)">
      <Text as="p" font="main-ui-action" color="text-03">
        {t("interruptedThinking.label")}
      </Text>
    </div>
  );
}
