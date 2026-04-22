import { Text, Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { cn } from "@/lib/utils";
import { QueuedMessage } from "@/app/app/interfaces";

interface QueuedMessageBarProps {
  messages: QueuedMessage[];
  highlightedIndex: number | null;
  awaitingPreferredSelection: boolean;
  onDiscard: (index: number) => void;
  onHighlight: (index: number | null) => void;
}

function QueuedMessageBar({
  messages,
  highlightedIndex,
  awaitingPreferredSelection,
  onDiscard,
  onHighlight,
}: QueuedMessageBarProps) {
  const isEmpty = messages.length === 0;

  return (
    <div
      className={cn(
        "transition-all duration-150",
        isEmpty ? "opacity-0 h-0 overflow-hidden" : "opacity-100"
      )}
    >
      {!isEmpty && (
        <div className="flex flex-col gap-1 pb-1.5">
          {messages.map((item, index) => {
            const isHighlighted = highlightedIndex === index;
            const showAwaitingLabel = awaitingPreferredSelection && index === 0;
            const showEditLabel = isHighlighted && !showAwaitingLabel;

            return (
              <div
                key={item.id}
                data-testid="queued-message-bar"
                className={cn(
                  "bg-background-neutral-02 rounded-12 border px-3 py-1.5 flex items-center gap-2 cursor-pointer",
                  isHighlighted ? "border-border-03" : "border-border-01"
                )}
                onClick={() => onHighlight(isHighlighted ? null : index)}
              >
                <div
                  className="flex-1 min-w-0 overflow-hidden whitespace-nowrap"
                  style={{
                    maskImage:
                      "linear-gradient(to right, black 80%, transparent 100%)",
                    WebkitMaskImage:
                      "linear-gradient(to right, black 80%, transparent 100%)",
                  }}
                >
                  <Text font="secondary-body" color="text-03">
                    {item.text}
                  </Text>
                </div>
                {showAwaitingLabel && (
                  <div className="flex-shrink-0 whitespace-nowrap">
                    <Text font="secondary-body" color="text-02">
                      Select a response to continue
                    </Text>
                  </div>
                )}
                {showEditLabel && (
                  <div className="flex-shrink-0 whitespace-nowrap flex items-center gap-0.5">
                    <span className="translate-y-[1.5px] text-text-02 text-[0.7rem]">
                      ↵
                    </span>
                    <Text font="secondary-body" color="text-02">
                      edit ·
                    </Text>
                    <span className="translate-y-[1.5px] text-text-02 text-[0.7rem]">
                      ⌫
                    </span>
                    <Text font="secondary-body" color="text-02">
                      remove
                    </Text>
                  </div>
                )}
                <Button
                  icon={SvgTrash}
                  prominence="tertiary"
                  size="xs"
                  tooltip="Remove queued message"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDiscard(index);
                  }}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default QueuedMessageBar;
