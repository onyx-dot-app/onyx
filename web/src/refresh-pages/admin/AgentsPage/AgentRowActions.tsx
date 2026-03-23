"use client";

import { useState } from "react";
import { Button } from "@opal/components";
// TODO(@raunakab): migrate to Opal LineItemButton once it supports danger variant
import LineItem from "@/refresh-components/buttons/LineItem";
import { Disabled } from "@opal/core";
import { cn } from "@opal/utils";
import {
  SvgMoreHorizontal,
  SvgEdit,
  SvgEye,
  SvgEyeClosed,
  SvgStar,
  SvgStarOff,
  SvgShare,
  SvgBarChart,
  SvgTrash,
  SvgAlertCircle,
} from "@opal/icons";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { useRouter } from "next/navigation";
import {
  deleteAgent,
  toggleAgentFeatured,
  toggleAgentListed,
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

  async function handleAction(action: () => Promise<void>) {
    setIsSubmitting(true);
    try {
      await action();
      onMutate();
      toast.success(`${agent.name} updated successfully.`);
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
        {/* TODO(@raunakab): abstract a more standardized way of doing this
            opacity-on-hover animation. Making Hoverable more extensible
            (e.g. supporting table row groups) would let us use it here
            instead of raw Tailwind group-hover. */}
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
        <div
          className={cn(
            !agent.is_featured &&
              "opacity-0 group-hover/row:opacity-100 transition-opacity"
          )}
        >
          <Button
            prominence="tertiary"
            icon={SvgStar}
            interaction={modal === Modal.TOGGLE_FEATURED ? "hover" : "rest"}
            tooltip={agent.is_featured ? "Remove Featured" : "Set as Featured"}
            onClick={() => openModal(Modal.TOGGLE_FEATURED)}
          />
        </div>

        {/* Overflow menu */}
        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <Popover.Trigger asChild>
            <Button prominence="tertiary" icon={SvgMoreHorizontal} />
          </Popover.Trigger>
          <Popover.Content align="end" width="sm">
            <PopoverMenu>
              {[
                <LineItem
                  key="visibility"
                  icon={agent.is_listed ? SvgEyeClosed : SvgEye}
                  onClick={() => {
                    setPopoverOpen(false);
                    handleAction(() =>
                      toggleAgentListed(agent.id, agent.is_listed)
                    );
                  }}
                >
                  {agent.is_listed ? "Hide Agent" : "Show Agent"}
                </LineItem>,
                <LineItem
                  key="share"
                  icon={SvgShare}
                  onClick={() => {
                    setPopoverOpen(false);
                  }}
                >
                  Share
                </LineItem>,
                <LineItem
                  key="stats"
                  icon={SvgBarChart}
                  onClick={() => {
                    setPopoverOpen(false);
                  }}
                >
                  Stats
                </LineItem>,
                !agent.builtin_persona ? null : undefined,
                !agent.builtin_persona ? (
                  <LineItem
                    key="delete"
                    icon={SvgTrash}
                    danger
                    onClick={() => openModal(Modal.DELETE)}
                  >
                    Delete
                  </LineItem>
                ) : undefined,
              ]}
            </PopoverMenu>
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
                  handleAction(() => deleteAgent(agent.id));
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
          icon={agent.is_featured ? SvgStarOff : SvgStar}
          title={
            agent.is_featured
              ? `Remove ${agent.name} from Featured`
              : `Feature ${agent.name}`
          }
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                onClick={() => {
                  handleAction(() =>
                    toggleAgentFeatured(agent.id, agent.is_featured)
                  );
                }}
              >
                {agent.is_featured ? "Unfeature" : "Feature"}
              </Button>
            </Disabled>
          }
        >
          <div className="flex flex-col gap-2">
            <Text as="p" text03>
              {agent.is_featured
                ? `This will remove ${agent.name} from the featured section on top of the explore agents list. New users will no longer see it pinned to their sidebar, but existing pins are unaffected.`
                : "Featured agents appear at the top of the explore agents list and are automatically pinned to the sidebar for new users with access. Use this to highlight recommended agents across your organization."}
            </Text>
            <Text as="p" text03>
              This does not change who can access this agent.
            </Text>
          </div>
        </ConfirmationModalLayout>
      )}
    </>
  );
}
