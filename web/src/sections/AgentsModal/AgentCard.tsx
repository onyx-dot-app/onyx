import React, { useState } from "react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverMenu,
} from "@/components/ui/popover";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useUser } from "@/components/user/UserProvider";
import { checkUserOwnsAssistant as checkUserOwnsAgent } from "@/lib/assistants/utils";
import { deletePersona } from "@/app/admin/assistants/lib";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import MenuButton from "@/refresh-components/buttons/MenuButton";
import SvgEditBig from "@/icons/edit-big";
import SvgTrash from "@/icons/trash";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import SvgBarChart from "@/icons/bar-chart";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import Button from "@/refresh-components/buttons/Button";
import { useAppRouter } from "@/hooks/appNavigation";

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
  const route = useAppRouter();
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
          submit={
            <Button danger onClick={confirmDelete}>
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this agent? This action cannot be
          undone.
        </ConfirmationModal>
      )}

      <div className="w-full h-full p-padding-content bg-background-tint-02 rounded-08">
        {popup}
        <div className="w-full h-full flex flex-row gap-spacing-paragraph">
          <AssistantIcon assistant={agent} size="large" />

          <div className="flex-1 flex flex-col gap-padding-button">
            <div className="flex flex-row justify-between items-center">
              <Truncated headingH3 text04>
                {agent.name}
              </Truncated>

              {isOwnedByUser && (
                <Popover open={kebabMenuOpen} onOpenChange={setKebabMenuOpen}>
                  <PopoverTrigger>
                    <div
                      className="w-[2rem] min-h-[2rem] hover:bg-background-tint-01 rounded-08 p-spacing-inline flex flex-col justify-center items-center"
                      data-testid="AgentCard/more"
                    >
                      <SvgMoreHorizontal className="w-[1rem] min-h-[1rem] stroke-text-04" />
                    </div>
                  </PopoverTrigger>

                  <PopoverContent>
                    <PopoverMenu>
                      {[
                        <div key="edit" data-testid="AgentCard/edit">
                          <MenuButton
                            icon={SvgEditBig}
                            href={`/assistants/edit/${agent.id}`}
                          >
                            Edit
                          </MenuButton>
                        </div>,
                        isPaidEnterpriseFeaturesEnabled ? (
                          <MenuButton
                            key="stats"
                            icon={SvgBarChart}
                            href={`/assistants/stats/${agent.id}`}
                          >
                            Stats
                          </MenuButton>
                        ) : undefined,
                        null,
                        <MenuButton
                          key="delete"
                          icon={SvgTrash}
                          onClick={() => {
                            setKebabMenuOpen(false);
                            setDeleteConfirmationModalOpen(true);
                          }}
                          danger
                        >
                          Delete
                        </MenuButton>,
                      ]}
                    </PopoverMenu>
                  </PopoverContent>
                </Popover>
              )}
            </div>

            <Text text03 className="flex-1">
              {agent.description}
            </Text>

            <div className="flex flex-row items-center gap-spacing-interline">
              <div className="max-w-[33%]">
                <Truncated secondaryBody text02>
                  By {agent.owner?.email || "Onyx"}
                </Truncated>
              </div>
              <Text secondaryBody text01>
                •
              </Text>
              <Text secondaryBody text02>
                {agent.tools.length > 0
                  ? `${agent.tools.length} Action${
                      agent.tools.length > 1 ? "s" : ""
                    }`
                  : "No Actions"}
              </Text>
              <Text secondaryBody text01>
                •
              </Text>
              <Text secondaryBody text02>
                {agent.is_public ? "Public" : "Private"}
              </Text>
            </div>

            <div className="flex gap-spacing-interline">
              <Button
                onClick={() => {
                  route({ agentId: agent.id });
                  closeModal();
                }}
                secondary
              >
                Start Chat
              </Button>
              <Button
                onClick={() => togglePinnedAgent(agent, !pinned)}
                secondary
              >
                {pinned ? "Unpin Agent" : "Pin Agent"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
