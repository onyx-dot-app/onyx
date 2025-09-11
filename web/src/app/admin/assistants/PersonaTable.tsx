"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

import Text from "@/components/ui/text";
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
import { TrashIcon } from "@/components/icons/icons";
import { useUser } from "@/components/user/UserProvider";
import { useAssistants } from "@/components/context/AssistantsContext";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";

function PersonaTypeDisplay({ persona }: { persona: Persona }) {
  if (persona.builtin_persona) {
    return <Text>{i18n.t(k.BUILT_IN2)}</Text>;
  }

  if (persona.is_default_persona) {
    return <Text>{i18n.t(k.DEFAULT2)}</Text>;
  }

  if (persona.is_public) {
    return <Text>{i18n.t(k.PUBLIC)}</Text>;
  }

  if (persona.groups.length > 0 || persona.users.length > 0) {
    return <Text>{i18n.t(k.SHARED)}</Text>;
  }

  return (
    <Text>
      {i18n.t(k.PERSONAL)}{" "}
      {persona.owner && (
        <>
          {i18n.t(k._4)}
          {persona.owner.email}
          {i18n.t(k._5)}
        </>
      )}
    </Text>
  );
}

export function PersonasTable() {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const { refreshUser, isAdmin } = useUser();
  const {
    allAssistants: assistants,
    refreshAssistants,
    editablePersonas,
  } = useAssistants();

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
    const nonEditable = assistants
      .filter((p) => !editablePersonaIds.has(p.id.toString()))
      .sort(personaComparator);
    setFinalPersonas([...editable, ...nonEditable]);
  }, [editablePersonas, assistants, editablePersonaIds]);

  const updatePersonaOrder = async (orderedPersonaIds: UniqueIdentifier[]) => {
    const reorderedAssistants = orderedPersonaIds.map(
      (id) => assistants.find((assistant) => assistant.id.toString() === id)!
    );

    setFinalPersonas(reorderedAssistants);

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
        message: i18n.t(k.FAILED_TO_UPDATE_PERSONA_ORDER, {
          response: await response.text(),
        }),
      });
      setFinalPersonas(assistants);
      await refreshAssistants();
      return;
    }

    await refreshAssistants();
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
        await refreshAssistants();
        closeDeleteModal();
      } else {
        setPopup({
          type: "error",
          message: i18n.t(k.FAILED_TO_DELETE_PERSONA, {
            response: await response.text(),
          }),
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
        await refreshAssistants();
        closeDefaultModal();
      } else {
        setPopup({
          type: "error",
          message: i18n.t(k.FAILED_TO_UPDATE_PERSONA, {
            response: await response.text(),
          }),
        });
      }
    }
  };

  return (
    <div>
      {popup}
      {deleteModalOpen && personaToDelete && (
        <ConfirmEntityModal
          entityType="Assistant"
          entityName={personaToDelete.name}
          onClose={closeDeleteModal}
          onSubmit={handleDeletePersona}
        />
      )}

      {defaultModalOpen && personaToToggleDefault && (
        <ConfirmEntityModal
          variant="action"
          entityType="Assistant"
          entityName={personaToToggleDefault.name}
          onClose={closeDefaultModal}
          onSubmit={handleToggleDefault}
          actionText={
            personaToToggleDefault.is_default_persona
              ? i18n.t(k.REMOVE_THE_FEATURED_STATUS_OF)
              : i18n.t(k.SET_AS_FEATURED)
          }
          actionButtonText={
            personaToToggleDefault.is_default_persona
              ? i18n.t(k.REMOVE_FEATURED)
              : i18n.t(k.SET_AS_FEATURED1)
          }
          additionalDetails={
            personaToToggleDefault.is_default_persona
              ? `${i18n.t(k.REMOVING)}${personaToToggleDefault.name}${i18n.t(
                  k.AS_A_FEATURED_ASSISTANT_WILL
                )}`
              : `${i18n.t(k.SETTING)}${personaToToggleDefault.name}${i18n.t(
                  k.AS_A_FEATURED_ASSISTANT_WILL1
                )}`
          }
        />
      )}

      <DraggableTable
        headers={[
          i18n.t(k.NAME),
          i18n.t(k.DESCRIPTION),
          i18n.t(k.TYPE),
          i18n.t(k.FAVORITE_ASSISTANT),
          i18n.t(k.VISIBILITY),
          i18n.t(k.DELETE),
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
                        `${i18n.t(k.ASSISTANTS_EDIT)}${persona.id}${i18n.t(
                          k.U
                        )}${Date.now()}${i18n.t(k.ADMIN_TRUE)}`
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
                  if (isEditable) {
                    openDefaultModal(persona);
                  }
                }}
                className={`px-1 py-0.5 rounded flex ${
                  isEditable
                    ? "hover:bg-accent-background-hovered cursor-pointer"
                    : ""
                } select-none w-fit`}
              >
                <div className="my-auto flex-none w-22">
                  {!persona.is_default_persona ? (
                    <div className="text-error">{i18n.t(k.NOT_FEATURED)}</div>
                  ) : (
                    i18n.t(k.FEATURED)
                  )}
                </div>
                <div className="ml-1 my-auto">
                  <CustomCheckbox checked={persona.is_default_persona} />
                </div>
              </div>,
              <div
                key="is_visible"
                onClick={async () => {
                  if (isEditable) {
                    const response = await togglePersonaVisibility(
                      persona.id,
                      persona.is_visible
                    );
                    if (response.ok) {
                      await refreshAssistants();
                    } else {
                      setPopup({
                        type: "error",
                        message: `${i18n.t(
                          k.FAILED_TO_UPDATE_PERSONA
                        )} ${await response.text()}`,
                      });
                    }
                  }
                }}
                className={`px-1 py-0.5 rounded flex ${
                  isEditable
                    ? "hover:bg-accent-background-hovered cursor-pointer"
                    : ""
                } select-none w-fit`}
              >
                <div className="my-auto w-12">
                  {!persona.is_visible ? (
                    <div className="text-error">{i18n.t(k.HIDDEN)}</div>
                  ) : (
                    i18n.t(k.VISIBLE)
                  )}
                </div>
                <div className="ml-1 my-auto">
                  <CustomCheckbox checked={persona.is_visible} />
                </div>
              </div>,
              <div key="edit" className="flex">
                <div className="mr-auto my-auto">
                  {!persona.builtin_persona && isEditable ? (
                    <div
                      className="hover:bg-accent-background-hovered rounded p-1 cursor-pointer"
                      onClick={() => openDeleteModal(persona)}
                    >
                      <TrashIcon />
                    </div>
                  ) : (
                    i18n.t(k._)
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
