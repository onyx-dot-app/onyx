"use client";

import React, { Dispatch, SetStateAction, useEffect, useState } from "react";
import { MinimalUserSnapshot, User } from "@/lib/types";
import { Persona } from "@/app/admin/assistants/interfaces";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  FiEdit2,
  FiList,
  FiMinus,
  FiMoreHorizontal,
  FiPlus,
  FiShare2,
  FiTrash,
  FiX,
} from "react-icons/fi";
import Link from "next/link";
import {
  addAssistantToList,
  removeAssistantFromList,
  updateUserAssistantList,
} from "@/lib/assistants/updateAssistantPreferences";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { DefaultPopover } from "@/components/popover/DefaultPopover";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { AssistantsPageTitle } from "../AssistantsPageTitle";
import { checkUserOwnsAssistant } from "@/lib/assistants/checkOwnership";
import { AssistantSharingModal } from "./AssistantSharingModal";
import { AssistantSharedStatusDisplay } from "../AssistantSharedStatus";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";

import { DragHandle } from "@/components/table/DragHandle";
import {
  deletePersona,
  togglePersonaPublicStatus,
} from "@/app/admin/assistants/lib";
import { DeleteEntityModal } from "@/components/modals/DeleteEntityModal";
import { MakePublicAssistantModal } from "@/app/chat/modal/MakePublicAssistantModal";
import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
import { useAssistants } from "@/components/context/AssistantsContext";
import { useUser } from "@/components/user/UserProvider";

function DraggableAssistantListItem(props: any) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: props.assistant.id.toString() });

  const style = {
    transform: transform
      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
      : undefined,
    transition,
    opacity: isDragging ? 0.9 : 1,
    zIndex: isDragging ? 1000 : "auto",
  };

  return (
    <div ref={setNodeRef} style={style} className="flex mt-2 items-center">
      <div {...attributes} {...listeners} className="mr-2 cursor-grab">
        <DragHandle />
      </div>
      <div className="flex-grow">
        <AssistantListItem isDragging={isDragging} {...props} />
      </div>
    </div>
  );
}

function AssistantListItem({
  assistant,
  user,
  allUsers,
  isVisible,
  setPopup,
  deleteAssistant,
  shareAssistant,
  isDragging,
}: {
  assistant: Persona;
  user: User | null;
  allUsers: MinimalUserSnapshot[];
  isVisible: boolean;
  deleteAssistant: Dispatch<SetStateAction<Persona | null>>;
  shareAssistant: Dispatch<SetStateAction<Persona | null>>;
  setPopup: (popupSpec: PopupSpec | null) => void;
  isDragging?: boolean;
}) {
  const { refreshUser } = useUser();
  const router = useRouter();
  const [showSharingModal, setShowSharingModal] = useState(false);

  const isOwnedByUser = checkUserOwnsAssistant(user, assistant);
  const currentChosenAssistants = user?.preferences
    ?.chosen_assistants as number[];

  return (
    <>
      <AssistantSharingModal
        assistant={assistant}
        user={user}
        allUsers={allUsers}
        onClose={() => {
          setShowSharingModal(false);
          router.refresh();
        }}
        show={showSharingModal}
      />
      <div
        className={`rounded-lg px-4 py-6 transition-all duration-900 hover:bg-background-125 ${
          isDragging && "bg-background-125"
        }`}
      >
        <div className="flex justify-between items-center">
          <AssistantIcon assistant={assistant} />

          <h2 className="ml-6 w-fit flex-grow space-y-3 text-start flex text-xl font-semibold line-clamp-2 text-gray-800">
            {assistant.name}
          </h2>

          <div className="flex flex-none items-center space-x-4">
            <div className="flex mr-20 flex-wrap items-center gap-x-4">
              {assistant.tools.length > 0 && (
                <p className="text-base flex w-fit text-subtle">
                  {assistant.tools.length} tool
                  {assistant.tools.length > 1 && "s"}
                </p>
              )}
              <AssistantSharedStatusDisplay
                size="md"
                assistant={assistant}
                user={user}
              />
            </div>

            {isOwnedByUser ? (
              <Link
                href={`/assistants/edit/${assistant.id}`}
                className="p-2 rounded-full hover:bg-gray-100 transition-colors duration-200"
                title="Edit assistant"
              >
                <FiEdit2 size={20} className="text-text-900" />
              </Link>
            ) : (
              <CustomTooltip
                showTick
                content="You don't have permission to edit this assistant"
              >
                <div className="p-2 cursor-not-allowed opacity-50 rounded-full hover:bg-gray-100 transition-colors duration-200">
                  <FiEdit2 size={20} className="text-text-900" />
                </div>
              </CustomTooltip>
            )}

            <DefaultPopover
              content={
                <div className="p-2 rounded-full hover:bg-gray-100 transition-colors duration-200 cursor-pointer">
                  <FiMoreHorizontal size={20} className="text-text-900" />
                </div>
              }
              side="bottom"
              align="end"
              sideOffset={5}
            >
              {[
                isVisible ? (
                  <button
                    key="remove"
                    className="flex items-center gap-x-2 px-4 py-2 hover:bg-gray-100 w-full text-left"
                    onClick={async () => {
                      if (currentChosenAssistants?.length === 1) {
                        setPopup({
                          message: `Cannot remove "${assistant.name}" - you must have at least one assistant.`,
                          type: "error",
                        });
                        return;
                      }
                      const success = await removeAssistantFromList(
                        assistant.id
                      );
                      if (success) {
                        setPopup({
                          message: `"${assistant.name}" has been removed from your list.`,
                          type: "success",
                        });
                        await refreshUser();
                      } else {
                        setPopup({
                          message: `"${assistant.name}" could not be removed from your list.`,
                          type: "error",
                        });
                      }
                    }}
                  >
                    <FiX size={18} className="text-text-800" />{" "}
                    {isOwnedByUser ? "Hide" : "Remove"}
                  </button>
                ) : (
                  <button
                    key="add"
                    className="flex items-center gap-x-2 px-4 py-2 hover:bg-gray-100 w-full text-left"
                    onClick={async () => {
                      const success = await addAssistantToList(assistant.id);
                      if (success) {
                        setPopup({
                          message: `"${assistant.name}" has been added to your list.`,
                          type: "success",
                        });
                        await refreshUser();
                      } else {
                        setPopup({
                          message: `"${assistant.name}" could not be added to your list.`,
                          type: "error",
                        });
                      }
                    }}
                  >
                    <FiPlus size={18} className="text-text-800" /> Add
                  </button>
                ),
                isOwnedByUser ? (
                  <button
                    key="delete"
                    className="flex items-center gap-x-2 px-4 py-2 hover:bg-gray-100 w-full text-left text-red-600"
                    onClick={() => deleteAssistant(assistant)}
                  >
                    <FiTrash size={18} /> Delete
                  </button>
                ) : null,
                isOwnedByUser ? (
                  <button
                    key="visibility"
                    className="flex items-center gap-x-2 px-4 py-2 hover:bg-gray-100 w-full text-left"
                    onClick={() => shareAssistant(assistant)}
                  >
                    {assistant.is_public ? (
                      <FiMinus size={18} className="text-text-800" />
                    ) : (
                      <FiPlus size={18} className="text-text-800" />
                    )}{" "}
                    Make {assistant.is_public ? "Private" : "Public"}
                  </button>
                ) : null,
                !assistant.is_public ? (
                  <button
                    key="share"
                    className="flex items-center gap-x-2 px-4 py-2 hover:bg-gray-100 w-full text-left"
                    onClick={(e) => {
                      setShowSharingModal(true);
                    }}
                  >
                    <FiShare2 size={18} className="text-text-800" /> Share
                  </button>
                ) : null,
              ]}
            </DefaultPopover>
          </div>
          {/* )} */}
        </div>
      </div>
    </>
  );
}
export function AssistantsList() {
  const {
    assistants,
    ownedButHiddenAssistants,
    finalAssistants,
    refreshAssistants,
  } = useAssistants();

  const [currentlyVisibleAssistants, setCurrentlyVisibleAssistants] =
    useState(finalAssistants);

  useEffect(() => {
    setCurrentlyVisibleAssistants(finalAssistants);
  }, [finalAssistants]);

  const allAssistantIds = assistants.map((assistant) =>
    assistant.id.toString()
  );

  const [deletingPersona, setDeletingPersona] = useState<Persona | null>(null);
  const [makePublicPersona, setMakePublicPersona] = useState<Persona | null>(
    null
  );

  const { refreshUser, user } = useUser();

  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const { data: users } = useSWR<MinimalUserSnapshot[]>(
    "/api/users",
    errorHandlingFetcher
  );

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      const oldIndex = currentlyVisibleAssistants.findIndex(
        (item) => item.id.toString() === active.id
      );
      const newIndex = currentlyVisibleAssistants.findIndex(
        (item) => item.id.toString() === over.id
      );
      const updatedAssistants = arrayMove(
        currentlyVisibleAssistants,
        oldIndex,
        newIndex
      );

      setCurrentlyVisibleAssistants(updatedAssistants);
      await updateUserAssistantList(updatedAssistants.map((a) => a.id));
      await refreshUser();
      await refreshAssistants();
    }
  }

  return (
    <>
      {popup}
      {deletingPersona && (
        <DeleteEntityModal
          entityType="Assistant"
          entityName={deletingPersona.name}
          onClose={() => setDeletingPersona(null)}
          onSubmit={async () => {
            const success = await deletePersona(deletingPersona.id);
            if (success) {
              setPopup({
                message: `"${deletingPersona.name}" has been deleted.`,
                type: "success",
              });
              await refreshUser();
            } else {
              setPopup({
                message: `"${deletingPersona.name}" could not be deleted.`,
                type: "error",
              });
            }
            setDeletingPersona(null);
          }}
        />
      )}

      {makePublicPersona && (
        <MakePublicAssistantModal
          isPublic={makePublicPersona.is_public}
          onClose={() => setMakePublicPersona(null)}
          onShare={async (newPublicStatus: boolean) => {
            await togglePersonaPublicStatus(
              makePublicPersona.id,
              newPublicStatus
            );
            await refreshAssistants();
          }}
        />
      )}

      <div className="mx-auto w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar">
        <AssistantsPageTitle>Your Assistants</AssistantsPageTitle>

        <div className="grid grid-cols-2 gap-4 mt-4 mb-8">
          <Button
            variant="default"
            className="p-6 text-base"
            onClick={() => router.push("/assistants/new")}
            icon={FiPlus}
          >
            Create New Assistant
          </Button>

          <Button
            onClick={() => router.push("/assistants/gallery")}
            variant="outline"
            className="text-base py-6"
            icon={FiList}
          >
            Assistant Gallery
          </Button>
        </div>

        <h2 className="text-2xl font-semibold mb-2 text-text-900">
          Active Assistants
        </h2>

        <h3 className="text-lg text-text-500">
          The order the assistants appear below will be the order they appear in
          the Assistants dropdown. The first assistant listed will be your
          default assistant when you start a new chat. Drag and drop to reorder.
        </h3>

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={currentlyVisibleAssistants.map((a) => a.id.toString())}
            strategy={verticalListSortingStrategy}
          >
            <div className="w-full items-center py-4">
              {currentlyVisibleAssistants.map((assistant, index) => (
                <DraggableAssistantListItem
                  deleteAssistant={setDeletingPersona}
                  shareAssistant={setMakePublicPersona}
                  key={assistant.id}
                  assistant={assistant}
                  user={user}
                  allAssistantIds={allAssistantIds}
                  allUsers={users || []}
                  isVisible
                  setPopup={setPopup}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>

        {ownedButHiddenAssistants.length > 0 && (
          <>
            <Separator />

            <h3 className="text-xl font-bold mb-4">Your Hidden Assistants</h3>

            <h3 className="text-lg text-text-500">
              Assistants you&apos;ve created that aren&apos;t currently visible
              in the Assistants selector.
            </h3>

            <div className="w-full p-4">
              {ownedButHiddenAssistants.map((assistant, index) => (
                <AssistantListItem
                  deleteAssistant={setDeletingPersona}
                  shareAssistant={setMakePublicPersona}
                  key={assistant.id}
                  assistant={assistant}
                  user={user}
                  allUsers={users || []}
                  isVisible={false}
                  setPopup={setPopup}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
