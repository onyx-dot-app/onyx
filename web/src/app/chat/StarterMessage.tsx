import { StarterMessage } from "../admin/assistants/interfaces";

export function StarterMessage({
  starterMessage,
  onClick,
}: {
  starterMessage: StarterMessage;
  onClick: () => void;
}) {
  return (
    <div
      className={
        "py-2 px-3 rounded border border-border bg-white cursor-pointer hover:bg-hover-light h-full"
      }
      onClick={onClick}
    >
      <p className="font-medium text-neutral-700">{starterMessage.name}</p>
      <p className="text-neutral-500 text-sm">{starterMessage.description}</p>
    </div>
  );
}
