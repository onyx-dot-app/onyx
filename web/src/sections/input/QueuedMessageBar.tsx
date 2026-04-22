import { Text, Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { cn } from "@/lib/utils";

interface QueuedMessageBarProps {
  messages: string[];
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
          {messages.map((message, index) => {
            const isHighlighted = highlightedIndex === index;
            const showAwaitingLabel = awaitingPreferredSelection && index === 0;
            const showEditLabel = isHighlighted && !showAwaitingLabel;

            return (
              <div
                key={index}
                data-testid="queued-message-bar"
                className={cn(
                  "bg-background-neutral-02 rounded-12 border px-3 py-1.5 flex items-center gap-2 cursor-pointer",
                  isHighlighted ? "border-border-03" : "border-border-01"
                )}
                onClick={() => onHighlight(isHighlighted ? null : index)}
              >
                <div className="flex-1 min-w-0">
                  <Text font="secondary-body" color="text-03" maxLines={1}>
                    {message}
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
                  <div className="flex-shrink-0 whitespace-nowrap">
                    <Text font="secondary-body" color="text-02">
                      Press Enter to edit
                    </Text>
                  </div>
                )}
                <Button
                  icon={SvgTrash}
                  prominence="tertiary"
                  size="xs"
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
