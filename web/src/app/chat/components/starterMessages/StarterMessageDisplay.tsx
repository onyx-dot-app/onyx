import { StarterMessage } from "@/app/admin/assistants/interfaces";
import Text from "@/components-2/Text";

export interface StarterMessageProps {
  starterMessages: StarterMessage[];
  onSelectStarterMessage: (message: string) => void;
}

export function StarterMessageDisplay({
  starterMessages,
  onSelectStarterMessage,
}: StarterMessageProps) {
  return (
    <div
      data-testid="starter-messages"
      className="flex flex-col w-full max-w-[40rem] p-spacing-inline gap-spacing-inline"
    >
      {starterMessages.map(({ name, message }, index) => (
        <button
          key={index}
          data-testid={`starter-message-${index}`}
          className="cursor-pointer bg-transparent hover:bg-background-tint-02 rounded-08 overflow-hidden text-ellipsis whitespace-nowrap p-padding-button"
          onClick={() => onSelectStarterMessage(message)}
        >
          <Text text03 className="text-left">
            {name}
          </Text>
        </button>
      ))}
    </div>
  );
}
