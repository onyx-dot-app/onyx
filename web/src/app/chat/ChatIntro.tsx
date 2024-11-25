import { Persona } from "../admin/assistants/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { useState } from "react";
import { DisplayAssistantCard } from "@/components/assistants/AssistantDescriptionCard";

export function ChatIntro({ selectedPersona }: { selectedPersona: Persona }) {
  const [hoveredAssistant, setHoveredAssistant] = useState(false);

  return (
    <div className="flex flex-col items-center gap-6">
      <div className="relative flex w-fit mx-auto justify-center">
        <div className="absolute z-10 -left-20 top-1/2 -translate-y-1/2">
          <div className="relative">
            <div
              onMouseEnter={() => setHoveredAssistant(true)}
              onMouseLeave={() => setHoveredAssistant(false)}
              className="p-4 scale-[.7] cursor-pointer border-dashed rounded-full flex border border-gray-300 border-2 border-dashed"
            >
              <AssistantIcon
                disableToolip
                size="large"
                assistant={selectedPersona}
              />
            </div>
            <div className="absolute right-full mr-1 w-[300px] top-0">
              {hoveredAssistant && (
                <DisplayAssistantCard selectedPersona={selectedPersona} />
              )}
            </div>
          </div>
        </div>

        <div className="text-2xl text-black font-semibold text-center">
          {selectedPersona.name}
        </div>
      </div>
      <p className="text-base text-black font-normal text-center">
        {selectedPersona.description}
      </p>
    </div>
  );
}
