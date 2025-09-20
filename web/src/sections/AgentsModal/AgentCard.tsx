import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { FiMoreHorizontal, FiTrash, FiEdit, FiBarChart } from "react-icons/fi";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";

import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useUser } from "@/components/user/UserProvider";
import { checkUserOwnsAssistant as checkUserOwnsAgent } from "@/lib/assistants/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { deletePersona } from "@/app/admin/assistants/lib";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useAgentsContext } from "@/components-2/context/AgentsContext";
import Text from "@/components-2/Text";
import Truncated from "@/components-2/Truncated";
import SvgBubbleText from "@/icons/bubble-text";
import SvgPin from "@/icons/pin";
import { SvgProps } from "@/icons";
import { MenuButton } from "../AppSidebar/components";
import SvgEditBig from "@/icons/edit-big";
import SvgTrash from "@/icons/trash";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import SvgBarChart from "@/icons/bar-chart";
import ConfirmationModal from "@/components-2/modals/ConfirmationModal";
import Button from "@/components-2/Button";

interface AgentActionButtonProps {
  title: string;
  icon: React.FunctionComponent<SvgProps>;
  onClick: () => void;
  tooltip: string;
}

function AgentActionButton({
  title,
  icon: Icon,
  onClick,
  tooltip,
}: AgentActionButtonProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={onClick}
            className="hover:bg-background-tint-03 p-spacing-interline gap-spacing-interline rounded-08 border flex items-center"
          >
            <Icon className="w-[1rem] h-[1rem] stroke-text-05" />
            <Text secondaryBody>{title}</Text>
          </button>
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

interface AgentCardProps {
  agent: MinimalPersonaSnapshot;
  pinned: boolean;
  closeModal: () => void;
}

export default function AgentCard({
  agent,
  pinned,
  closeModal,
}: AgentCardProps) {
  const router = useRouter();
  const { user } = useUser();
  const { togglePinnedAgent, refreshAgents } = useAgentsContext();
  const { popup, setPopup } = usePopup();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const [kebabMenuOpen, setKebabMenuOpen] = useState(false);
  const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
    useState(false);
  const isOwnedByUser = checkUserOwnsAgent(user, agent);

  async function confirmDelete() {
    const response = await deletePersona(agent.id);
    if (response.ok) {
      await refreshAgents();
      setDeleteConfirmationModalOpen(false);
      setPopup({
        message: `${agent.name} has been successfully deleted.`,
        type: "success",
      });
    } else {
      setPopup({
        message: `Failed to delete agent - ${await response.text()}`,
        type: "error",
      });
    }
  }

  return (
    <>
      {deleteConfirmationModalOpen && (
        <ConfirmationModal
          title="Delete Agent"
          icon={SvgTrash}
          onClose={() => setDeleteConfirmationModalOpen(false)}
          description="Are you sure you want to delete this agent? This action cannot be undone."
        >
          <Button
            secondary
            onClick={() => setDeleteConfirmationModalOpen(false)}
          >
            Cancel
          </Button>
          <Button danger onClick={confirmDelete}>
            Delete
          </Button>
        </ConfirmationModal>
      )}

      <div className="w-full h-full p-padding-content bg-background-tint-02 rounded-08">
        {popup}
        <div className="w-full h-full flex flex-row gap-spacing-paragraph">
          <AssistantIcon assistant={agent} size="large" />

          <div className="flex-1 flex flex-col gap-padding-button">
            <div className="flex flex-row justify-between items-center">
              <Truncated>
                <Text headingH3 text04>
                  {agent.name}
                </Text>
              </Truncated>

              {isOwnedByUser && (
                <Popover open={kebabMenuOpen} onOpenChange={setKebabMenuOpen}>
                  <PopoverTrigger>
                    <div className="w-[2rem] min-h-[2rem] hover:bg-background-tint-01 rounded-08 p-spacing-inline flex flex-col justify-center items-center">
                      <SvgMoreHorizontal className="w-[1rem] min-h-[1rem] stroke-text-04" />
                    </div>
                  </PopoverTrigger>

                  <PopoverContent>
                    <div className="flex flex-col gap-spacing-inline">
                      <MenuButton
                        icon={SvgEditBig}
                        onClick={() =>
                          router.push(`/assistants/edit/${agent.id}`)
                        }
                      >
                        Edit
                      </MenuButton>
                      {isPaidEnterpriseFeaturesEnabled && (
                        <MenuButton
                          icon={SvgBarChart}
                          onClick={() =>
                            router.push(`/assistants/stats/${agent.id}`)
                          }
                        >
                          Stats
                        </MenuButton>
                      )}
                      <MenuButton
                        icon={SvgTrash}
                        onClick={() => {
                          setKebabMenuOpen(false);
                          setDeleteConfirmationModalOpen(true);
                        }}
                        danger
                      >
                        Delete
                      </MenuButton>
                    </div>
                  </PopoverContent>
                </Popover>
              )}
            </div>

            <Text text03 className="flex-1">
              {agent.description}
            </Text>

            <div className="flex flex-row items-center gap-spacing-interline">
              <div className="max-w-[33%]">
                <Truncated>
                  <Text secondaryBody text02>
                    By {agent.owner?.email || "Onyx"} asdf
                  </Text>
                </Truncated>
              </div>
              <Text secondaryBody text01>
                •
              </Text>
              <Text secondaryBody text02>
                {agent.tools.length > 0
                  ? `${agent.tools.length} Action${agent.tools.length > 1 ? "s" : ""}`
                  : "No Actions"}
              </Text>
              <Text secondaryBody text01>
                •
              </Text>
              <Text secondaryBody text02>
                {agent.is_public ? "Public" : "Private"}
              </Text>
            </div>

            <div className="flex gap-2">
              <AgentActionButton
                title="Start Chat"
                icon={SvgBubbleText}
                onClick={() => {
                  router.push(
                    `/chat?${SEARCH_PARAM_NAMES.PERSONA_ID}=${agent.id}`
                  );
                  closeModal();
                }}
                tooltip="Start a new chat with this agent"
              />
              <AgentActionButton
                title={pinned ? "Unpin" : "Pin"}
                icon={SvgPin}
                onClick={() => togglePinnedAgent(agent, !pinned)}
                tooltip={`${pinned ? "Remove from" : "Add to"} your pinned list`}
              />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
