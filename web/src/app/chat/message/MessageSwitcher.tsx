import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/Text";
import SvgChevronLeft from "@/icons/chevron-left";
import SvgChevronRight from "@/icons/chevron-right";

const DISABLED_MESSAGE = "Wait for agent message to complete";

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
  const handle = (num: number, callback: () => void) =>
    disableForStreaming
      ? undefined
      : currentPage === num
        ? undefined
        : callback;
  const previous = handle(1, handlePrevious);
  const next = handle(totalPages, handleNext);

  return (
    <div className="flex flex-row items-center gap-spacing-inline">
      <IconButton
        icon={SvgChevronLeft}
        onClick={previous}
        tertiary
        disabled={disableForStreaming}
        tooltip={disableForStreaming ? DISABLED_MESSAGE : "Previous"}
      />

      <div className="flex flex-row items-center justify-center">
        <Text text03 mainAction>
          {currentPage}
        </Text>
        <Text text03 mainAction>
          /
        </Text>
        <Text text03 mainAction>
          {totalPages}
        </Text>
      </div>

      <IconButton
        icon={SvgChevronRight}
        onClick={next}
        tertiary
        disabled={disableForStreaming}
        tooltip={disableForStreaming ? DISABLED_MESSAGE : "Next"}
      />
    </div>
  );
}
