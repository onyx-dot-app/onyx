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
  SvgEyeOff,
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
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [featuredOpen, setFeaturedOpen] = useState(false);
  const [unlistOpen, setUnlistOpen] = useState(false);

  async function handleAction(action: () => Promise<void>, close: () => void) {
    setIsSubmitting(true);
    try {
      await action();
      onMutate();
      toast.success(`${agent.name} updated successfully.`);
      close();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  }

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
        {!agent.is_listed ? (
          <Button
            prominence="tertiary"
            icon={SvgEyeOff}
            tooltip="Re-list Agent"
            onClick={() =>
              handleAction(
                () => toggleAgentListed(agent.id, agent.is_listed),
                () => {}
              )
            }
          />
        ) : (
          <div
            className={cn(
              !agent.is_featured &&
                "opacity-0 group-hover/row:opacity-100 transition-opacity"
            )}
          >
            <Button
              prominence="tertiary"
              icon={SvgStar}
              interaction={featuredOpen ? "hover" : "rest"}
              tooltip={
                agent.is_featured ? "Remove Featured" : "Set as Featured"
              }
              onClick={() => {
                setPopoverOpen(false);
                setFeaturedOpen(true);
              }}
            />
          </div>
        )}

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
                  icon={agent.is_listed ? SvgEyeOff : SvgEye}
                  onClick={() => {
                    setPopoverOpen(false);
                    if (agent.is_listed) {
                      setUnlistOpen(true);
                    } else {
                      handleAction(
                        () => toggleAgentListed(agent.id, agent.is_listed),
                        () => {}
                      );
                    }
                  }}
                >
                  {agent.is_listed ? "Unlist Agent" : "List Agent"}
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
                    onClick={() => {
                      setPopoverOpen(false);
                      setDeleteOpen(true);
                    }}
                  >
                    Delete
                  </LineItem>
                ) : undefined,
              ]}
            </PopoverMenu>
          </Popover.Content>
        </Popover>
      </div>

      {deleteOpen && (
        <ConfirmationModalLayout
          icon={(props) => (
            <SvgAlertCircle {...props} className="text-action-danger-05" />
          )}
          title="Delete Agent"
          onClose={isSubmitting ? undefined : () => setDeleteOpen(false)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={() => {
                  handleAction(
                    () => deleteAgent(agent.id),
                    () => setDeleteOpen(false)
                  );
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

      {featuredOpen && (
        <ConfirmationModalLayout
          icon={agent.is_featured ? SvgStarOff : SvgStar}
          title={
            agent.is_featured
              ? `Remove ${agent.name} from Featured`
              : `Feature ${agent.name}`
          }
          onClose={isSubmitting ? undefined : () => setFeaturedOpen(false)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                onClick={() => {
                  handleAction(
                    () => toggleAgentFeatured(agent.id, agent.is_featured),
                    () => setFeaturedOpen(false)
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

      {unlistOpen && (
        <ConfirmationModalLayout
          icon={SvgEyeOff}
          title={`Unlist ${agent.name}`}
          onClose={isSubmitting ? undefined : () => setUnlistOpen(false)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                onClick={() => {
                  handleAction(
                    () => toggleAgentListed(agent.id, agent.is_listed),
                    () => setUnlistOpen(false)
                  );
                }}
              >
                Unlist
              </Button>
            </Disabled>
          }
        >
          <div className="flex flex-col gap-2">
            <Text as="p" text03>
              Unlisted agents don&apos;t appear in the explore agents list but
              remain accessible via direct link, and to users who have
              previously used or pinned them.
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
