import { StarterMessage } from "@/app/admin/assistants/interfaces";

export function StarterMessageDisplay({
  starterMessages,
  onSelectStarterMessage,
}: {
  starterMessages: StarterMessage[];
  onSelectStarterMessage: (message: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2 w-full max-w-searchbar-max mx-auto">
      {starterMessages.map((starterMessage) => (
        <div
          key={starterMessage.name}
          onClick={() => onSelectStarterMessage(starterMessage.message)}
          className="
            text-left 
            text-text-500 
            text-sm 
            mx-7 
            px-2 
            py-2 
            hover:bg-background-100 
            dark:hover:bg-neutral-800
            rounded-lg 
            cursor-pointer
            overflow-hidden
            text-ellipsis
            whitespace-nowrap
          "
        >
          {starterMessage.name}
        </div>
      ))}
    </div>
  );
}
