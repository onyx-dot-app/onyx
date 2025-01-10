import React, { useCallback, useState } from "react";
import { Persona } from "@/app/admin/assistants/interfaces";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { OnyxIcon, PinnedIcon } from "@/components/icons/icons";
import { FaHashtag } from "react-icons/fa";
import {
  FiShare2,
  FiEye,
  FiEyeOff,
  FiTrash,
  FiMoreHorizontal,
  FiEdit,
} from "react-icons/fi";
import { toggleAssistantPinnedStatus } from "@/lib/assistants/updateAssistantPreferences";
import { useAssistants } from "@/components/context/AssistantsContext";
import { useUser } from "@/components/user/UserProvider";
import { useRouter } from "next/navigation";
import { checkUserOwnsAssistant } from "@/lib/assistants/checkOwnership";
import { AssistantSharingModal } from "../mine/AssistantSharingModal";
import {
  togglePersonaPublicStatus,
  deletePersona,
} from "@/app/admin/assistants/lib";
import { DeleteEntityModal } from "@/components/modals/DeleteEntityModal";
import { MakePublicAssistantModal } from "@/app/chat/modal/MakePublicAssistantModal";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";

export const AssistantBadge = ({ text }: { text: string }) => {
  return (
    <div className="h-4 px-1.5 py-1 bg-[#e6e3dd]/50 rounded-lg justify-center items-center gap-2.5 inline-flex">
      <div className="text-[#4a4a4a] text-[10px] font-normal leading-[8px]">
        {text}
      </div>
    </div>
  );
};

const NewAssistantCard: React.FC<{
  persona: Persona;
  pinned: boolean;
  closeModal: () => void;
}> = ({ persona, pinned, closeModal }) => {
  const { user, refreshUser } = useUser();
  const router = useRouter();
  const { refreshAssistants } = useAssistants();
  const [showSharingModal, setShowSharingModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showPublicModal, setShowPublicModal] = useState(false);

  const isOwnedByUser = checkUserOwnsAssistant(user, persona);

  const [isPopoverOpen, setIsPopoverOpen] = useState(false);

  const closePopover = useCallback(() => {
    setIsPopoverOpen(false);
  }, []);
  const handleShare = () => {
    setShowSharingModal(true);
    closePopover();
  };
  const handleToggleVisibility = () => {
    setShowPublicModal(true);
    closePopover();
  };
  const handleDelete = () => {
    setShowDeleteModal(true);
    closePopover();
  };
  const handleEdit = () => {
    router.push(`/assistants/edit/${persona.id}`);
    closePopover();
  };

  return (
    <div className="w-full p-2 overflow-visible bg-[#fefcf9] rounded shadow-[0px_0px_4px_0px_rgba(0,0,0,0.25)] flex">
      <div className="ml-2 mr-4 mt-1 w-8 h-8">
        <AssistantIcon assistant={persona} size="large" />
      </div>
      <div className="flex-1 flex flex-col">
        <div className="flex justify-between items-start mb-1">
          <div className="flex items-end gap-x-2 leading-none">
            <h3 className="text-black leading-none text-base lg-normal">
              {persona.name}
            </h3>
            <AssistantBadge text={persona.is_public ? "Public" : "Private"} />
          </div>
          {pinned && <span className="text-[#6c6c6c] h-0 text-sm">Pinned</span>}
        </div>

        <p className="text-black text-sm mb-1 line-clamp-2 h-[2.7em]">
          {persona.description || "\u00A0"}
        </p>

        <div className="mb-1">
          {persona.tools.length > 0 ? (
            <>
              <span className="text-black text-sm mr-1">Tools</span>
              {persona.tools.map((tool, index) => (
                <AssistantBadge key={index} text={tool.name} />
              ))}
            </>
          ) : (
            <AssistantBadge text="No Tools" />
          )}
        </div>

        <div className="mb-1 flex flex-wrap">
          {persona.document_sets.slice(0, 5).map((set, index) => (
            <AssistantBadge key={index} text={set.name} />
          ))}
        </div>

        <div className="flex items-center justify-between mt-2">
          <div className="flex gap-2">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => {
                      router.push(`/chat?assistantId=${persona.id}`);
                      closeModal();
                    }}
                    className="hover:bg-neutral-100 px-2 py-1 gap-x-1 rounded border border-black flex items-center"
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
                      await toggleAssistantPinnedStatus(persona.id, !pinned);
                      await refreshUser();
                    }}
                    className="hover:bg-neutral-100 px-2 py-1 gap-x-1 rounded border border-black flex items-center"
                  >
                    <PinnedIcon size={12} />
                    <span className="text-xs">{pinned ? "Unpin" : "Pin"}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent>
                  {pinned ? "Remove from" : "Add to"} your pinned list
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          {isOwnedByUser && (
            <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="hover:bg-neutral-100 p-1 rounded-full"
                >
                  <FiMoreHorizontal size={16} />
                </button>
              </PopoverTrigger>
              <PopoverContent className="z-[10000] w-40 p-2">
                <button
                  onClick={handleShare}
                  className="w-full text-left flex items-center px-2 py-1 hover:bg-neutral-100 rounded"
                >
                  <FiShare2 size={12} className="inline mr-2" />
                  Share
                </button>
                <button
                  onClick={handleToggleVisibility}
                  className="w-full text-left flex items-center px-2 py-1 hover:bg-neutral-100 rounded"
                >
                  {persona.is_public ? (
                    <FiEyeOff size={12} className="inline mr-2" />
                  ) : (
                    <FiEye size={12} className="inline mr-2" />
                  )}
                  Make {persona.is_public ? "Private" : "Public"}
                </button>
                <button
                  onClick={handleDelete}
                  className="w-full text-left items-center px-2 py-1 hover:bg-neutral-100 rounded text-red-600"
                >
                  <FiTrash size={12} className="inline mr-2" />
                  Delete
                </button>
                <button
                  onClick={handleEdit}
                  className="w-full flex items-center text-left px-2 py-1 hover:bg-neutral-100 rounded"
                >
                  <FiEdit size={12} className="inline mr-2" />
                  Edit
                </button>
              </PopoverContent>
            </Popover>
          )}
        </div>
      </div>

      {showSharingModal && (
        <AssistantSharingModal
          assistant={persona}
          user={user}
          allUsers={[]}
          onClose={() => {
            setShowSharingModal(false);
            refreshAssistants();
          }}
          show={showSharingModal}
        />
      )}

      {showDeleteModal && (
        <DeleteEntityModal
          entityType="Assistant"
          entityName={persona.name}
          onClose={() => setShowDeleteModal(false)}
          onSubmit={async () => {
            const success = await deletePersona(persona.id);
            if (success) {
              await refreshAssistants();
            }
          }}
        />
      )}

      {showPublicModal && (
        <MakePublicAssistantModal
          isPublic={persona.is_public}
          onClose={() => setShowPublicModal(false)}
          onShare={async (newPublicStatus: boolean) => {
            await togglePersonaPublicStatus(persona.id, newPublicStatus);
            await refreshAssistants();
          }}
        />
      )}
    </div>
  );
};

export default NewAssistantCard;
