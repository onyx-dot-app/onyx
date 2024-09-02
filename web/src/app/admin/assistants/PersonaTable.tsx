"use client";

import { Persona } from "./interfaces";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { UniqueIdentifier } from "@dnd-kit/core";
import { DraggableTable } from "@/components/table/DraggableTable";
import { deletePersona, personaComparator } from "./lib";
import { TrashIcon } from "@/components/icons/icons";
import { Pencil } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

function PersonaTypeDisplay({ persona }: { persona: Persona }) {
  if (persona.default_persona) {
    return <p>Built-In</p>;
  }

  if (persona.is_public) {
    return <p>Global</p>;
  }

  return <p>Personal {persona.owner && <>({persona.owner.email})</>}</p>;
}

export function PersonasTable({ personas }: { personas: Persona[] }) {
  const router = useRouter();
  const { toast } = useToast();

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
      toast({
        title: "Error",
        description: `Failed to update persona order - ${await response.text()}`,
        variant: "destructive",
      });
      router.refresh();
    }
  };

  return (
    <div>
      <p className="pb-6">
        Assistants will be displayed as options on the Chat / Search interfaces
        in the order they are displayed below. Assistants marked as hidden will
        not be displayed.
      </p>

      <Card>
        <CardContent className="p-0">
          <DraggableTable
            headers={["Name", "Description", "Type", "Is Visible", "Delete"]}
            rows={finalPersonaValues.map((persona) => {
              return {
                id: persona.id.toString(),
                cells: [
                  <div key="name" className="flex gap-2 items-center">
                    {!persona.default_persona && (
                      <Button variant="ghost" size="icon">
                        <Pencil
                          size={16}
                          onClick={() =>
                            router.push(
                              `/admin/assistants/${persona.id}?u=${Date.now()}`
                            )
                          }
                        />
                      </Button>
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
                  <Badge
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
                        toast({
                          title: "Error",
                          description: `Failed to update persona - ${await response.text()}`,
                          variant: "destructive",
                        });
                      }
                    }}
                    variant="outline"
                    className="py-1.5 px-3 w-[84px]"
                  >
                    {!persona.is_visible ? (
                      <div className="text-error">Hidden</div>
                    ) : (
                      "Visible"
                    )}

                    <Checkbox checked={persona.is_visible} />
                  </Badge>,
                  <div key="edit" className="flex">
                    <div className="mx-auto my-auto">
                      {!persona.default_persona ? (
                        <Button
                          variant="ghost"
                          size="icon"
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
                        </Button>
                      ) : (
                        "-"
                      )}
                    </div>
                  </div>,
                ],
                staticModifiers: [
                  [1, "lg:w-sidebar xl:w-[400px] 2xl:w-[550px]"],
                ],
              };
            })}
            setRows={updatePersonaOrder}
          />
        </CardContent>
      </Card>
    </div>
  );
}
