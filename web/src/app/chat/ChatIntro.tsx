import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { MinimalPersonaSnapshot } from "../admin/assistants/interfaces";

export function ChatIntro({
  selectedPersona,
}: {
  selectedPersona: MinimalPersonaSnapshot;
}) {
  return (
    <div data-testid="chat-intro" className="flex flex-col items-center gap-6">
      <div className="relative flex flex-col gap-y-4 w-fit mx-auto justify-center">
        <div className="absolute z-10 items-center flex -left-12 top-1/2 -translate-y-1/2">
          <AssistantIcon size={36} assistant={selectedPersona} />
        </div>

        <div className="text-4xl text-text font-normal text-center">
          {selectedPersona.name}
        </div>
      </div>
      <div className="self-stretch text-center text-text-darker text-xl font-[350] leading-normal">
        {selectedPersona.description}
      </div>
    </div>
  );
}
