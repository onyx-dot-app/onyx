import { Persona } from "@/app/admin/assistants/interfaces";
import { BasicSelectable } from "@/components/BasicClickable";
import { User } from "@/lib/types";
import { Text } from "@tremor/react";
import Link from "next/link";
import { FiEdit } from "react-icons/fi";

function AssistantDisplay({
  persona,
  onSelect,
  user,
}: {
  persona: Persona;
  onSelect: (persona: Persona) => void;
  user: User | null;
}) {
  const isEditable =
    (!user || user.id === persona.owner?.id) &&
    !persona.default_persona &&
    (!persona.is_public || !user || user.role === "admin");

  return (
    <div className="flex">
      <div className="w-full" onClick={() => onSelect(persona)}>
        <BasicSelectable selected={false} fullWidth>
          <div className="flex">
            <div className="truncate w-48 3xl:w-56">{persona.name}</div>
          </div>
        </BasicSelectable>
      </div>
      {isEditable && (
        <div className="pl-2 my-auto">
          <Link href={`/assistants/edit/${persona.id}`}>
            <FiEdit
              className="my-auto ml-auto hover:bg-hover p-0.5"
              size={20}
            />
          </Link>
        </div>
      )}
    </div>
  );
}

export function AssistantsTab({
  personas,
  onPersonaChange,
  user,
}: {
  personas: Persona[];
  onPersonaChange: (persona: Persona | null) => void;
  user: User | null;
}) {
  const globalAssistants = personas.filter((persona) => persona.is_public);
  const personalAssistants = personas.filter(
    (persona) =>
      !user || (persona.users.includes(user.id) && !persona.is_public)
  );

  return (
    <div className="mt-4 pb-1 overflow-y-auto h-full flex flex-col gap-y-1">
      <Text className="mx-3 text-xs mb-4">
        Select an Assistant below to begin a new chat with them!
      </Text>

      <div className="mx-3">
        {globalAssistants.length > 0 && (
          <>
            <div className="text-xs text-subtle flex pb-0.5 ml-1 mb-1.5 font-bold">
              Global
            </div>
            {globalAssistants.map((persona) => {
              return (
                <AssistantDisplay
                  key={persona.id}
                  persona={persona}
                  onSelect={onPersonaChange}
                  user={user}
                />
              );
            })}
          </>
        )}

        {personalAssistants.length > 0 && (
          <>
            <div className="text-xs text-subtle flex pb-0.5 ml-1 mb-1.5 mt-5 font-bold">
              Personal
            </div>
            {personalAssistants.map((persona) => {
              return (
                <AssistantDisplay
                  key={persona.id}
                  persona={persona}
                  onSelect={onPersonaChange}
                  user={user}
                />
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
