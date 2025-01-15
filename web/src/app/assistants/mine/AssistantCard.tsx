import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  FiMoreHorizontal,
  FiShare2,
  FiEye,
  FiEyeOff,
  FiTrash,
  FiEdit,
  FiHash,
  FiBarChart,
  FiLock,
  FiUnlock,
  FiSearch,
} from "react-icons/fi";
import { FaHashtag } from "react-icons/fa";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { AssistantVisibilityPopover } from "./AssistantVisibilityPopover";
import { DeleteAssistantPopover } from "./DeleteAssistantPopover";
import { Persona } from "@/app/admin/assistants/interfaces";
import { useUser } from "@/components/user/UserProvider";
import { useAssistants } from "@/components/context/AssistantsContext";
import { checkUserOwnsAssistant } from "@/lib/assistants/utils";
import { toggleAssistantPinnedStatus } from "@/lib/assistants/pinnedAssistants";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { PinnedIcon } from "@/components/icons/icons";
import {
  deletePersona,
  togglePersonaPublicStatus,
} from "@/app/admin/assistants/lib";
import { HammerIcon } from "lucide-react";

export const AssistantBadge = ({
  text,
  className,
}: {
  text: string;
  className?: string;
}) => {
  return (
    <div
      className={`h-4 px-1.5 py-1 text-[10px]  bg-[#e6e3dd]/50 rounded-lg justify-center items-center gap-1 inline-flex ${className}`}
    >
      <div className="text-[#4a4a4a] font-normal leading-[8px]">{text}</div>
    </div>
  );
};

const AssistantCard: React.FC<{
  persona: Persona;
  pinned: boolean;
  closeModal: () => void;
}> = ({ persona, pinned, closeModal }) => {
  const { user, refreshUser } = useUser();
  const router = useRouter();
  const { refreshAssistants } = useAssistants();

  const isOwnedByUser = checkUserOwnsAssistant(user, persona);

  const [activePopover, setActivePopover] = useState<string | null | undefined>(
    undefined
  );

  const handleShare = () => setActivePopover("visibility");
  const handleDelete = () => setActivePopover("delete");
  const handleEdit = () => {
    router.push(`/assistants/edit/${persona.id}`);
    setActivePopover(null);
  };

  const closePopover = () => setActivePopover(undefined);

  return (
    <div className="w-full p-2 overflow-visible pb-4 pt-3 bg-[#fefcf9] rounded shadow-[0px_0px_4px_0px_rgba(0,0,0,0.25)] flex flex-col">
      <div className="w-full flex">
        <div className="ml-2 mr-4 mt-1 w-8 h-8">
          <AssistantIcon assistant={persona} size="large" />
        </div>
        <div className="flex-1 mt-1 flex flex-col">
          <div className="flex justify-between items-start mb-1">
            <div className="flex items-end gap-x-2 leading-none">
              <h3 className="text-black leading-none font-semibold text-base lg-normal">
                {persona.name}
              </h3>
              {persona.labels && persona.labels.length > 0 && (
                <>
                  {persona.labels.slice(0, 3).map((label, index) => (
                    <AssistantBadge key={index} text={label.name} />
                  ))}
                  {persona.labels.length > 3 && (
                    <AssistantBadge
                      text={`+${persona.labels.length - 3} more`}
                    />
                  )}
                </>
              )}
            </div>
            {isOwnedByUser && (
              <div className="flex items-center gap-x-2">
                <Popover
                  open={activePopover !== undefined}
                  onOpenChange={(open) =>
                    open ? setActivePopover(null) : setActivePopover(undefined)
                  }
                >
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      className="hover:bg-neutral-100 p-1 -my-1 rounded-full"
                    >
                      <FiMoreHorizontal size={16} />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent
                    className={`z-[10000] ${
                      activePopover === null ? "w-32" : "w-80"
                    } p-2`}
                  >
                    {activePopover === null && (
                      <div className="flex flex-col text-sm space-y-1">
                        <button
                          onClick={isOwnedByUser ? handleEdit : undefined}
                          className={`w-full flex items-center text-left px-2 py-1 rounded ${
                            isOwnedByUser
                              ? "hover:bg-neutral-100"
                              : "opacity-50 cursor-not-allowed"
                          }`}
                          disabled={!isOwnedByUser}
                        >
                          <FiEdit size={12} className="inline mr-2" />
                          Edit
                        </button>
                        {/* 
                        <button
                          onClick={isOwnedByUser ? handleShare : undefined}
                          className={`w-full text-left flex items-center px-2 py-1 rounded ${
                            isOwnedByUser
                              ? "hover:bg-neutral-100"
                              : "opacity-50 cursor-not-allowed"
                          }`}
                          disabled={!isOwnedByUser}
                        >
                          <FiShare2 size={12} className="inline mr-2" />
                          Share
                        </button> */}

                        <button
                          onClick={
                            isOwnedByUser
                              ? () => {
                                  router.push(
                                    `/assistants/stats/${persona.id}`
                                  );
                                  closePopover();
                                }
                              : undefined
                          }
                          className={`w-full text-left items-center px-2 py-1 rounded ${
                            isOwnedByUser
                              ? "hover:bg-neutral-100"
                              : "opacity-50 cursor-not-allowed"
                          }`}
                          disabled={!isOwnedByUser}
                        >
                          <FiBarChart size={12} className="inline mr-2" />
                          Stats
                        </button>
                        <button
                          onClick={isOwnedByUser ? handleDelete : undefined}
                          className={`w-full text-left items-center px-2 py-1 rounded ${
                            isOwnedByUser
                              ? "hover:bg-neutral-100 text-red-600"
                              : "opacity-50 cursor-not-allowed text-red-300"
                          }`}
                          disabled={!isOwnedByUser}
                        >
                          <FiTrash size={12} className="inline mr-2" />
                          Delete
                        </button>
                      </div>
                    )}
                    {activePopover === "visibility" && (
                      <AssistantVisibilityPopover
                        assistant={persona}
                        user={user}
                        allUsers={[]}
                        onClose={closePopover}
                        onTogglePublic={async (isPublic: boolean) => {
                          await togglePersonaPublicStatus(persona.id, isPublic);
                          await refreshAssistants();
                        }}
                      />
                    )}
                    {activePopover === "delete" && (
                      <DeleteAssistantPopover
                        entityName={persona.name}
                        onClose={closePopover}
                        onSubmit={async () => {
                          const success = await deletePersona(persona.id);
                          if (success) {
                            await refreshAssistants();
                          }
                          closePopover();
                        }}
                      />
                    )}
                  </PopoverContent>
                </Popover>
              </div>
            )}
          </div>

          <p className="text-black font-[350] mt-0 text-sm mb-1 line-clamp-2 h-[2.7em]">
            {persona.description || "\u00A0"}
          </p>

          <div className="flex flex-col ">
            {/* <div className="mb-1 mt-1">
              <div className="flex items-center">
               
              </div>
            </div> */}

            <div className="my-1">
              <span className="flex items-center text-black text-xs opacity-50">
                {(persona.owner?.email || persona.builtin_persona) && "By "}
                {persona.owner?.email || (persona.builtin_persona && "Onyx")}
                {(persona.owner?.email || persona.builtin_persona) && (
                  <span className="mx-2">•</span>
                )}
                {persona.tools.length > 0 ? (
                  <>
                    {persona.tools.length}
                    {" Action"}
                    {persona.tools.length !== 1 ? "s" : ""}
                  </>
                ) : (
                  "No Actions"
                )}
                <span className="mx-2">•</span>
                {persona.is_public ? (
                  <>
                    <FiUnlock size={12} className="inline mr-1" />
                    Public
                  </>
                ) : (
                  <>
                    <FiLock size={12} className="inline mr-1" />
                    Private
                  </>
                )}
              </span>
            </div>

            <div className="mb-1 flex flex-wrap">
              {persona.document_sets.slice(0, 5).map((set, index) => (
                <AssistantBadge
                  className="!text-base"
                  key={index}
                  text={set.name}
                />
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => {
                      router.push(`/chat?assistantId=${persona.id}`);
                      closeModal();
                    }}
                    className="hover:bg-neutral-100 hover:text-text px-2 py-1 gap-x-1 rounded border border-black flex items-center"
                  >
                    <FaHashtag size={12} className="flex-none" />
                    <span className="text-xs">Start Chat</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent>
                  Start a new chat with this assistant
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={async () => {
                      await toggleAssistantPinnedStatus(
                        user?.preferences.pinned_assistants || [],
                        persona.id,
                        !pinned
                      );
                      await refreshUser();
                    }}
                    className="hover:bg-neutral-100 px-2 py-1 gap-x-1 rounded border border-black flex items-center"
                    style={{ width: "65px" }}
                  >
                    <PinnedIcon size={12} />
                    <p className="text-xs">{pinned ? "Unpin" : "Pin"}</p>
                  </button>
                </TooltipTrigger>
                <TooltipContent>
                  {pinned ? "Remove from" : "Add to"} your pinned list
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-center"></div>
    </div>
  );
};

export default AssistantCard;
