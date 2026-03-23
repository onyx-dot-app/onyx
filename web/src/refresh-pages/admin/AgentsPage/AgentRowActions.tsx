"use client";

import { useState } from "react";
import { Button, LineItemButton } from "@opal/components";
import { Disabled } from "@opal/core";
import {
  SvgMoreHorizontal,
  SvgEdit,
  SvgEye,
  SvgEyeClosed,
  SvgStar,
  SvgShare,
  SvgBarChart,
  SvgTrash,
  SvgAlertCircle,
} from "@opal/icons";
import Popover from "@/refresh-components/Popover";
import Divider from "@/refresh-components/Divider";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { useRouter } from "next/navigation";
import {
  deleteAgent,
  toggleAgentFeatured,
  toggleAgentVisibility,
} from "@/refresh-pages/admin/AgentsPage/svc";
import type { AgentRow } from "@/refresh-pages/admin/AgentsPage/interfaces";
import type { Route } from "next";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

enum Modal {
  DELETE = "delete",
  TOGGLE_FEATURED = "toggleFeatured",
}

interface AgentRowActionsProps {
  agent: AgentRow;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AgentRowActions({
  agent,
  onMutate,
}: AgentRowActionsProps) {
  const router = useRouter();
  const [modal, setModal] = useState<Modal | null>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleAction(
    action: () => Promise<void>,
    successMessage: string
  ) {
    setIsSubmitting(true);
    try {
      await action();
      onMutate();
      toast.success(successMessage);
      setModal(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  }

  const openModal = (type: Modal) => {
    setPopoverOpen(false);
    setModal(type);
  };

  return (
    <>
      <div className="flex items-center gap-0.5">
        {!agent.builtin_persona && (
          <div className="opacity-0 group-hover/row:opacity-100 transition-opacity">
            <Button
              prominence="tertiary"
              icon={SvgEdit}
              tooltip="Edit Agent"
              onClick={() =>
                router.push(
                  `/app/agents/edit/${
                    agent.id
                  }?u=${Date.now()}&admin=true` as Route
                )
              }
            />
          </div>
        )}
        <div className="opacity-0 group-hover/row:opacity-100 transition-opacity">
          <Button
            prominence="tertiary"
            icon={SvgStar}
            tooltip={agent.featured ? "Remove Featured" : "Set as Featured"}
            onClick={() => openModal(Modal.TOGGLE_FEATURED)}
          />
        </div>

        {/* Overflow menu */}
        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <Popover.Trigger asChild>
            <Button prominence="tertiary" icon={SvgMoreHorizontal} />
          </Popover.Trigger>
          <Popover.Content align="end" width="sm">
            <Popover.Menu>
              <LineItemButton
                icon={agent.is_visible ? SvgEyeClosed : SvgEye}
                title={agent.is_visible ? "Hide Agent" : "Show Agent"}
                sizePreset="main-ui"
                onClick={() => {
                  setPopoverOpen(false);
                  handleAction(
                    () => toggleAgentVisibility(agent.id, agent.is_visible),
                    agent.is_visible ? "Agent hidden" : "Agent visible"
                  );
                }}
              />
              <LineItemButton
                icon={SvgShare}
                title="Share"
                sizePreset="main-ui"
                onClick={() => {
                  setPopoverOpen(false);
                }}
              />
              <LineItemButton
                icon={SvgBarChart}
                title="Stats"
                sizePreset="main-ui"
                onClick={() => {
                  setPopoverOpen(false);
                }}
              />
              {!agent.builtin_persona && (
                <>
                  <Divider />
                  <LineItemButton
                    icon={SvgTrash}
                    title="Delete Agent"
                    sizePreset="main-ui"
                    onClick={() => openModal(Modal.DELETE)}
                  />
                </>
              )}
            </Popover.Menu>
          </Popover.Content>
        </Popover>
      </div>

      {modal === Modal.DELETE && (
        <ConfirmationModalLayout
          icon={(props) => (
            <SvgAlertCircle {...props} className="text-action-danger-05" />
          )}
          title="Delete Agent"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={() => {
                  handleAction(() => deleteAgent(agent.id), "Agent deleted");
                }}
              >
                Delete
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            Are you sure you want to delete{" "}
            <Text as="span" text05>
              {agent.name}
            </Text>
            ? This action cannot be undone.
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === Modal.TOGGLE_FEATURED && (
        <ConfirmationModalLayout
          icon={SvgStar}
          title={
            agent.featured ? "Remove Featured Agent" : "Set Featured Agent"
          }
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                onClick={() => {
                  handleAction(
                    () => toggleAgentFeatured(agent.id, agent.featured),
                    agent.featured
                      ? "Agent removed from featured"
                      : "Agent set as featured"
                  );
                }}
              >
                {agent.featured ? "Remove Featured" : "Set as Featured"}
              </Button>
            </Disabled>
          }
        >
          <div className="flex flex-col gap-2">
            <Text as="p" text03>
              {agent.featured
                ? `Are you sure you want to remove the featured status of "${agent.name}"?`
                : `Are you sure you want to set "${agent.name}" as a featured agent?`}
            </Text>
            <Text as="p" text03>
              {agent.featured
                ? "Removing featured status will not affect its visibility or accessibility."
                : "Setting as featured will make this agent public and visible to all users."}
            </Text>
          </div>
        </ConfirmationModalLayout>
      )}
    </>
  );
}
