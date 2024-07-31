"use client";

import { Text } from "@tremor/react";
import { Persona } from "./interfaces";
import { useRouter } from "next/navigation";
import { CustomCheckbox } from "@/components/CustomCheckbox";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { UniqueIdentifier } from "@dnd-kit/core";
import { DraggableTable } from "@/components/table/DraggableTable";
import { deletePersona, personaComparator } from "./lib";
import { FiEdit2 } from "react-icons/fi";
import { TrashIcon } from "@/components/icons/icons";

function PersonaTypeDisplay({ persona }: { persona: Persona }) {
  if (persona.default_persona) {
    return <Text>Built-In</Text>;
  }

  if (persona.is_public) {
    return <Text>Global</Text>;
  }

  if (persona.groups.length > 0 || persona.users.length > 0) {
    return <Text>Shared</Text>;
  }

  return <Text>Personal {persona.owner && <>({persona.owner.email})</>}</Text>;
}

export function PersonasTable({ personas }: { personas: Persona[] }) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const availablePersonaIds = new Set(
    personas.map((persona) => persona.id.toString())
  );
  const sortedPersonas = [...personas];
  sortedPersonas.sort(personaComparator);

  const [finalPersonas, setFinalPersonas] = useState<string[]>(
    sortedPersonas.map((persona) => persona.id.toString())
  );
  const finalPersonaValues = finalPersonas
    .filter((id) => availablePersonaIds.has(id))
    .map((id) => {
      return sortedPersonas.find(
        (persona) => persona.id.toString() === id
      ) as Persona;
    });

  const updatePersonaOrder = async (orderedPersonaIds: UniqueIdentifier[]) => {
    setFinalPersonas(orderedPersonaIds.map((id) => id.toString()));

    const displayPriorityMap = new Map<UniqueIdentifier, number>();
    orderedPersonaIds.forEach((personaId, ind) => {
      displayPriorityMap.set(personaId, ind);
    });

    const response = await fetch("/api/admin/persona/display-priority", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        display_priority_map: Object.fromEntries(displayPriorityMap),
      }),
    });
    if (!response.ok) {
      setPopup({
        type: "error",
        message: `Failed to update persona order - ${await response.text()}`,
      });
      router.refresh();
    }
  };

  return (
    <div>
      {popup}

      <Text className="my-2">
        Assistants will be displayed as options on the Chat / Search interfaces
        in the order they are displayed below. Assistants marked as hidden will
        not be displayed.
      </Text>

      <DraggableTable
        headers={["Name", "Description", "Type", "Is Visible", "Delete"]}
        rows={finalPersonaValues.map((persona) => {
          return {
            id: persona.id.toString(),
            cells: [
              <div key="name" className="flex">
                {!persona.default_persona && (
                  <FiEdit2
                    className="mr-1 my-auto cursor-pointer"
                    onClick={() =>
                      router.push(
                        `/admin/assistants/${persona.id}?u=${Date.now()}`
                      )
                    }
                  />
                )}
                <p className="text font-medium whitespace-normal break-none">
                  {persona.name}
                </p>
              </div>,
              <p
                key="description"
                className="whitespace-normal break-all max-w-2xl"
              >
                {persona.description}
              </p>,
              <PersonaTypeDisplay key={persona.id} persona={persona} />,
              <div
                key="is_visible"
                onClick={async () => {
                  const response = await fetch(
                    `/api/admin/persona/${persona.id}/visible`,
                    {
                      method: "PATCH",
                      headers: {
                        "Content-Type": "application/json",
                      },
                      body: JSON.stringify({
                        is_visible: !persona.is_visible,
                      }),
                    }
                  );
                  if (response.ok) {
                    router.refresh();
                  } else {
                    setPopup({
                      type: "error",
                      message: `Failed to update persona - ${await response.text()}`,
                    });
                  }
                }}
                className="px-1 py-0.5 hover:bg-hover-light rounded flex cursor-pointer select-none w-fit"
              >
                <div className="my-auto w-12">
                  {!persona.is_visible ? (
                    <div className="text-error">Hidden</div>
                  ) : (
                    "Visible"
                  )}
                </div>
                <div className="ml-1 my-auto">
                  <CustomCheckbox checked={persona.is_visible} />
                </div>
              </div>,
              <div key="edit" className="flex">
                <div className="mx-auto my-auto">
                  {!persona.default_persona ? (
                    <div
                      className="hover:bg-hover rounded p-1 cursor-pointer"
                      onClick={async () => {
                        const response = await deletePersona(persona.id);
                        if (response.ok) {
                          router.refresh();
                        } else {
                          alert(
                            `Failed to delete persona - ${await response.text()}`
                          );
                        }
                      }}
                    >
                      <TrashIcon />
                    </div>
                  ) : (
                    "-"
                  )}
                </div>
              </div>,
            ],
            staticModifiers: [[1, "lg:w-[250px] xl:w-[400px] 2xl:w-[550px]"]],
          };
        })}
        setRows={updatePersonaOrder}
      />
    </div>
  );
}
