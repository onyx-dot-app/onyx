"use client";

import { Text } from "@tremor/react";
import { Persona } from "./interfaces";
import { useRouter } from "next/navigation";
import { CustomCheckbox } from "@/components/CustomCheckbox";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState, useMemo, useEffect } from "react";
import { UniqueIdentifier } from "@dnd-kit/core";
import { DraggableTable } from "@/components/table/DraggableTable";
import { deletePersona, personaComparator } from "./lib";
import { FiEdit2 } from "react-icons/fi";
import { TrashIcon } from "@/components/icons/icons";
import { getCurrentUser } from "@/lib/user";
import { UserRole, User } from "@/lib/types";
import { useUser } from "@/components/user/UserProvider";

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

const togglePersonaVisibility = async (
  personaId: number,
  isVisible: boolean
) => {
  const response = await fetch(`/api/admin/persona/${personaId}/visible`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      is_visible: !isVisible,
    }),
  });
  return response;
};

export function PersonasTable({
  allPersonas,
  editablePersonas,
}: {
  allPersonas: Persona[];
  editablePersonas: Persona[];
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const { isLoadingUser, isAdmin } = useUser();

  const editablePersonaIds = new Set(
    editablePersonas.map((p) => p.id.toString())
  );

  const sortedPersonas = useMemo(() => {
    const editable = editablePersonas.sort(personaComparator);
    const nonEditable = allPersonas
      .filter((p) => !editablePersonaIds.has(p.id.toString()))
      .sort(personaComparator);
    return [...editable, ...nonEditable];
  }, [allPersonas, editablePersonas]);

  const [finalPersonas, setFinalPersonas] = useState<string[]>(
    sortedPersonas.map((persona) => persona.id.toString())
  );
  const finalPersonaValues = finalPersonas
    .filter((id) => new Set(allPersonas.map((p) => p.id.toString())).has(id))
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

  if (isLoadingUser) {
    return <></>;
  }

  return (
    <div>
      {popup}

      <Text className="my-2">
        Assistants will be displayed as options on the Chat / Search interfaces
        in the order they are displayed below. Assistants marked as hidden will
        not be displayed. Editable assistants are shown at the top.
      </Text>

      <DraggableTable
        headers={["Name", "Description", "Type", "Is Visible", "Delete"]}
        isAdmin={isAdmin}
        rows={finalPersonaValues.map((persona) => {
          const isEditable = editablePersonaIds.has(persona.id.toString());
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
                  if (isEditable) {
                    const response = await togglePersonaVisibility(
                      persona.id,
                      persona.is_visible
                    );
                    if (response.ok) {
                      router.refresh();
                    } else {
                      setPopup({
                        type: "error",
                        message: `Failed to update persona - ${await response.text()}`,
                      });
                    }
                  }
                }}
                className={`px-1 py-0.5 rounded flex ${isEditable ? "hover:bg-hover cursor-pointer" : ""} select-none w-fit`}
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
                  {!persona.default_persona && isEditable ? (
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
