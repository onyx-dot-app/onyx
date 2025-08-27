import { StarterMessage } from "@/app/admin/assistants/interfaces";

export function StarterMessageDisplay({
  starterMessages,
}: {
  starterMessages: StarterMessage[];
}) {
  return (
    <div className="flex flex-col gap-2 w-full max-w-searchbar-max mx-auto">
      {starterMessages.map((starterMessage) => (
        <div
          key={starterMessage.name}
          className="
            text-left 
            text-text-500 
            text-sm 
            mx-3 
            px-2 
            py-2 
            hover:bg-background-100 
            rounded-lg 
            cursor-pointer
            overflow-hidden
            text-ellipsis
            whitespace-nowrap
            max-w-[50%]
          "
        >
          {starterMessage.message}
        </div>
      ))}
    </div>
  );
}
