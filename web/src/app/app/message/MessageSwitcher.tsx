import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import { useTranslations } from "next-intl";

interface MessageSwitcherProps {
  currentPage: number;
  totalPages: number;
  handlePrevious: () => void;
  handleNext: () => void;
  disableForStreaming?: boolean;
}

export default function MessageSwitcher({
  currentPage,
  totalPages,
  handlePrevious,
  handleNext,
  disableForStreaming,
}: MessageSwitcherProps) {
  const t = useTranslations("chat.messages");
  const disabledTooltip = t("messageSwitcher.disabledWhileStreaming.tooltip");
  const handle = (num: number, callback: () => void) =>
    disableForStreaming
      ? undefined
      : currentPage === num
        ? undefined
        : callback;
  const previous = handle(1, handlePrevious);
  const next = handle(totalPages, handleNext);

  return (
    <div
      className="flex flex-row items-center gap-1"
      data-testid="MessageSwitcher/container"
    >
      <Button
        disabled={disableForStreaming}
        icon={SvgChevronLeft}
        onClick={previous}
        prominence="tertiary"
        tooltip={
          disableForStreaming
            ? disabledTooltip
            : t("messageSwitcher.previousButton.tooltip")
        }
      />

      <div className="flex flex-row items-center justify-center">
        <Text as="p" text03 mainUiAction>
          {currentPage}
        </Text>
        <Text as="p" text03 mainUiAction>
          /
        </Text>
        <Text as="p" text03 mainUiAction>
          {totalPages}
        </Text>
      </div>

      <Button
        disabled={disableForStreaming}
        icon={SvgChevronRight}
        onClick={next}
        prominence="tertiary"
        tooltip={
          disableForStreaming
            ? disabledTooltip
            : t("messageSwitcher.nextButton.tooltip")
        }
      />
    </div>
  );
}
