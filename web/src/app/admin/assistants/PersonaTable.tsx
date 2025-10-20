"use client";

import Text from "@/refresh-components/texts/Text";
import { Persona } from "./interfaces";
import { useRouter } from "next/navigation";
import { CustomCheckbox } from "@/components/CustomCheckbox";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState, useMemo, useEffect } from "react";
import { UniqueIdentifier } from "@dnd-kit/core";
import { DraggableTable } from "@/components/table/DraggableTable";
import {
  deletePersona,
  personaComparator,
  togglePersonaDefault,
  togglePersonaVisibility,
} from "./lib";
import { FiEdit2 } from "react-icons/fi";
import { useUser } from "@/components/user/UserProvider";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgTrash from "@/icons/trash";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import SvgAlertCircle from "@/icons/alert-circle";
import Button from "@/refresh-components/buttons/Button";

function PersonaTypeDisplay({ persona }: { persona: Persona }) {
  if (persona.builtin_persona) {
    return <Text>Built-In</Text>;
  }

  if (persona.is_default_persona) {
    return <Text>Default</Text>;
  }

  if (persona.is_public) {
    return <Text>Public</Text>;
  }

  if (persona.groups.length > 0 || persona.users.length > 0) {
    return <Text>Shared</Text>;
  }

  return <Text>Personal {persona.owner && <>({persona.owner.email})</>}</Text>;
}

export function PersonasTable({
  personas,
  refreshPersonas,
}: {
  personas: Persona[];
  refreshPersonas: () => void;
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const { refreshUser, isAdmin } = useUser();

  const editablePersonas = useMemo(() => {
    return personas.filter((p) => !p.builtin_persona);
  }, [personas]);

  const editablePersonaIds = useMemo(() => {
    return new Set(editablePersonas.map((p) => p.id.toString()));
  }, [editablePersonas]);

  const [finalPersonas, setFinalPersonas] = useState<Persona[]>([]);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [personaToDelete, setPersonaToDelete] = useState<Persona | null>(null);
  const [defaultModalOpen, setDefaultModalOpen] = useState(false);
  const [personaToToggleDefault, setPersonaToToggleDefault] =
    useState<Persona | null>(null);

  useEffect(() => {
    const editable = editablePersonas.sort(personaComparator);
    const nonEditable = personas
      .filter((p) => !editablePersonaIds.has(p.id.toString()))
      .sort(personaComparator);
    setFinalPersonas([...editable, ...nonEditable]);
  }, [editablePersonas, personas, editablePersonaIds]);

  const updatePersonaOrder = async (orderedPersonaIds: UniqueIdentifier[]) => {
    const reorderedPersonas = orderedPersonaIds.map(
      (id) => personas.find((persona) => persona.id.toString() === id)!
    );

    setFinalPersonas(reorderedPersonas);

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
      setFinalPersonas(personas);
      await refreshPersonas();
      return;
    }

    await refreshPersonas();
    await refreshUser();
  };

  const openDeleteModal = (persona: Persona) => {
    setPersonaToDelete(persona);
    setDeleteModalOpen(true);
  };

  const closeDeleteModal = () => {
    setDeleteModalOpen(false);
    setPersonaToDelete(null);
  };

  const handleDeletePersona = async () => {
    if (personaToDelete) {
      const response = await deletePersona(personaToDelete.id);
      if (response.ok) {
        refreshPersonas();
        closeDeleteModal();
      } else {
        setPopup({
          type: "error",
          message: `Failed to delete persona - ${await response.text()}`,
        });
      }
    }
  };

  const openDefaultModal = (persona: Persona) => {
    setPersonaToToggleDefault(persona);
    setDefaultModalOpen(true);
  };

  const closeDefaultModal = () => {
    setDefaultModalOpen(false);
    setPersonaToToggleDefault(null);
  };

  const handleToggleDefault = async () => {
    if (personaToToggleDefault) {
      const response = await togglePersonaDefault(
        personaToToggleDefault.id,
        personaToToggleDefault.is_default_persona
      );
      if (response.ok) {
        refreshPersonas();
        closeDefaultModal();
      } else {
        setPopup({
          type: "error",
          message: `Failed to update persona - ${await response.text()}`,
        });
      }
    }
  };

  return (
    <div>
      {popup}
      {deleteModalOpen && personaToDelete && (
        <ConfirmationModal
          icon={SvgAlertCircle}
          title="Delete Assistant"
          onClose={closeDeleteModal}
          submit={<Button onClick={handleDeletePersona}>Delete</Button>}
        >
          {`Are you sure you want to delete ${personaToDelete.name}?`}
        </ConfirmationModal>
      )}
      {defaultModalOpen &&
        personaToToggleDefault &&
        (() => {
          const isDefault = personaToToggleDefault.is_default_persona;

          const title = isDefault
            ? "Remove Featured Assistant"
            : "Set Featurd Assistant";
          const buttonText = isDefault ? "Remove Feature" : "Set as Featured";
          const text = isDefault
            ? `Are you sure you want to remove the featured status of ${personaToToggleDefault.name}?`
            : `Are you sure you want to set the featured status of ${personaToToggleDefault.name}?`;
          const additionalText = isDefault
            ? `Removing "${personaToToggleDefault.name}" as a featured assistant will not affect its visibility or accessibility.`
            : `Setting "${personaToToggleDefault.name}" as a featured assistant will make it public and visible to all users. This action cannot be undone.`;

          return (
            <ConfirmationModal
              icon={SvgAlertCircle}
              title={title}
              onClose={closeDefaultModal}
              submit={
                <Button onClick={handleToggleDefault}>{buttonText}</Button>
              }
            >
              <div className="flex flex-col gap-spacing-interline">
                <Text>{text}</Text>
                <Text text03>{additionalText}</Text>
              </div>
            </ConfirmationModal>
          );
        })()}

      <DraggableTable
        headers={[
          "Name",
          "Description",
          "Type",
          "Featured Assistant",
          "Is Visible",
          "Delete",
        ]}
        isAdmin={isAdmin}
        rows={finalPersonas.map((persona) => {
          const isEditable = editablePersonas.includes(persona);
          return {
            id: persona.id.toString(),
            cells: [
              <div key="name" className="flex">
                {!persona.builtin_persona && (
                  <FiEdit2
                    className="mr-1 my-auto cursor-pointer"
                    onClick={() =>
                      router.push(
                        `/assistants/edit/${
                          persona.id
                        }?u=${Date.now()}&admin=true`
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
                key="is_default_persona"
                onClick={() => {
                  openDefaultModal(persona);
                }}
                className={`px-1 py-0.5 rounded flex hover:bg-accent-background-hovered cursor-pointer select-none w-fit`}
              >
                <div className="my-auto flex-none w-22">
                  {!persona.is_default_persona ? (
                    <div className="text-error">Not Featured</div>
                  ) : (
                    "Featured"
                  )}
                </div>
                <div className="ml-1 my-auto">
                  <CustomCheckbox checked={persona.is_default_persona} />
                </div>
              </div>,
              <div
                key="is_visible"
                onClick={async () => {
                  const response = await togglePersonaVisibility(
                    persona.id,
                    persona.is_visible
                  );
                  if (response.ok) {
                    refreshPersonas();
                  } else {
                    setPopup({
                      type: "error",
                      message: `Failed to update persona - ${await response.text()}`,
                    });
                  }
                }}
                className={`px-1 py-0.5 rounded flex hover:bg-accent-background-hovered cursor-pointer select-none w-fit`}
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
                <div className="mr-auto my-auto">
                  {!persona.builtin_persona && isEditable ? (
                    <IconButton
                      icon={SvgTrash}
                      tertiary
                      onClick={() => openDeleteModal(persona)}
                    />
                  ) : (
                    <Text>-</Text>
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
