"use client";

import { useNavigation } from "@opal/navigation";
import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  Text,
  useCreateModal,
  type DropdownMenuItem,
} from "@opal/components";
// TODO(@raunakab): migrate to Opal LineItemButton once it supports danger variant
import { cn, escapeMarkdown, markdown, richNodes } from "@opal/utils";
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
} from "@opal/icons";
import { ConfirmationModalLayout } from "@opal/layouts";
import { toast } from "@opal/layouts";
import {
  deleteAgent,
  toggleAgentFeatured,
  toggleAgentListed,
} from "@/lib/agents/svc";
import type { Agent } from "@/lib/agents/types";
import { ShareAgentModal } from "@/lib/agents/components";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import { can } from "@/lib/permissions/resource-actions";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentRowActionsProps {
  agent: Agent;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AgentRowActions({
  agent,
  onMutate,
}: AgentRowActionsProps) {
  const t = useTranslations("admin.agents");
  const navigation = useNavigation();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const shareModal = useCreateModal();

  // Gate on the list row's stamped permissions so controls render immediately, rather
  // than waiting on a per-row fetch.
  const canEdit = can(agent, "edit");
  const canList = can(agent, "list");
  const canUpdateFeaturedStatus = can(agent, "feature");
  const canShare = can(agent, "share");
  const canViewStats = can(agent, "view_stats");
  const canDeleteRow = !agent.builtin_persona && can(agent, "delete");
  const hasOverflowItems =
    canList || canShare || (businessTier && canViewStats) || canDeleteRow;

  const [menuOpen, setMenuOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const deleteModal = useCreateModal();
  const featuredModal = useCreateModal();
  // The featured state the confirm was opened for. The list refetches before
  // the card finishes fading out, which would flip its copy mid-exit.
  const [wasFeatured, setWasFeatured] = useState(agent.is_featured);
  const unlistModal = useCreateModal();

  async function handleAction(action: () => Promise<void>, close: () => void) {
    setIsSubmitting(true);
    try {
      await action();
      onMutate();
      toast.success(
        t("rowActions.updateSuccess.message", { name: agent.name })
      );
      close();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("rowActions.genericError.message")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const menuItems: DropdownMenuItem[] = [
    ...(canList
      ? [
          {
            kind: "action" as const,
            id: "visibility",
            icon: agent.is_listed ? SvgEyeOff : SvgEye,
            title: agent.is_listed
              ? t("rowActions.unlistItem.title")
              : t("rowActions.listItem.title"),
            onSelect: () => {
              if (agent.is_listed) {
                unlistModal.toggle(true);
              } else {
                handleAction(
                  () => toggleAgentListed(agent.id, agent.is_listed),
                  () => {}
                );
              }
            },
          },
        ]
      : []),
    ...(canShare
      ? [
          {
            kind: "action" as const,
            id: "share",
            icon: SvgShare,
            title: t("rowActions.shareItem.title"),
            onSelect: () => shareModal.toggle(true),
          },
        ]
      : []),
    ...(businessTier && canViewStats
      ? [
          {
            kind: "action" as const,
            id: "stats",
            icon: SvgBarChart,
            title: t("rowActions.statsItem.title"),
            onSelect: () => navigation.go(`/ee/agents/stats/${agent.id}`),
          },
        ]
      : []),
    ...(canDeleteRow
      ? [
          {
            kind: "action" as const,
            id: "delete",
            icon: SvgTrash,
            danger: true,
            title: t("rowActions.deleteItem.title"),
            onSelect: () => deleteModal.toggle(true),
          },
        ]
      : []),
  ];

  return (
    <>
      <shareModal.Provider>
        {/* Saved agents persist sharing inside the dialog itself */}
        <ShareAgentModal agentId={agent.id} />
      </shareModal.Provider>

      <div
        className="flex items-center gap-0.5"
        data-testid={`agent-row-actions-${agent.id}`}
      >
        {/* TODO(@raunakab): abstract a more standardized way of doing this
            appear-on-hover animation. Making Hoverable more extensible
            (e.g. supporting table row groups) would let us use it here
            instead of raw Tailwind group-hover. */}
        {!agent.builtin_persona && canEdit && (
          <div className="opacity-0 group-hover/row:opacity-100 transition-opacity">
            <Button
              prominence="tertiary"
              icon={SvgEdit}
              tooltip={t("rowActions.editAgentButton.label")}
              aria-label={t("rowActions.editAgentButton.label")}
              data-testid={`edit-agent-${agent.id}`}
              onClick={() =>
                navigation.go(
                  `/app/agents/edit/${agent.id}?u=${Date.now()}&admin=true`
                )
              }
            />
          </div>
        )}
        {!agent.is_listed
          ? canList && (
              <Button
                prominence="tertiary"
                icon={SvgEyeOff}
                tooltip={t("rowActions.relistAgentButton.label")}
                aria-label={t("rowActions.relistAgentButton.label")}
                onClick={() =>
                  handleAction(
                    () => toggleAgentListed(agent.id, agent.is_listed),
                    () => {}
                  )
                }
              />
            )
          : canUpdateFeaturedStatus && (
              <div
                className={cn(
                  !agent.is_featured &&
                    "opacity-0 group-hover/row:opacity-100 transition-opacity"
                )}
              >
                <Button
                  prominence="tertiary"
                  icon={SvgStar}
                  interaction={featuredModal.isOpen ? "hover" : "rest"}
                  tooltip={
                    agent.is_featured
                      ? t("rowActions.removeFeaturedButton.label")
                      : t("rowActions.setFeaturedButton.label")
                  }
                  aria-label={
                    agent.is_featured
                      ? t("rowActions.removeFeaturedButton.label")
                      : t("rowActions.setFeaturedButton.label")
                  }
                  onClick={() => {
                    setMenuOpen(false);
                    setWasFeatured(agent.is_featured);
                    featuredModal.toggle(true);
                  }}
                />
              </div>
            )}

        {/* Overflow menu */}
        {hasOverflowItems && (
          <Dropdown open={menuOpen} onOpenChange={setMenuOpen}>
            <div
              className={cn(
                !menuOpen &&
                  "opacity-0 group-hover/row:opacity-100 transition-opacity"
              )}
            >
              <Dropdown.Trigger asChild>
                <Button
                  prominence="tertiary"
                  icon={SvgMoreHorizontal}
                  aria-label={t("rowActions.menuButton.ariaLabel")}
                />
              </Dropdown.Trigger>
            </div>
            <Dropdown.Data
              label={t("rowActions.menuButton.ariaLabel")}
              items={menuItems}
            />
          </Dropdown>
        )}
      </div>

      <deleteModal.Provider>
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("deleteModal.header.title")}
          onClose={isSubmitting ? undefined : () => deleteModal.toggle(false)}
          submit={
            <Button
              disabled={isSubmitting}
              variant="danger"
              onClick={() => {
                handleAction(
                  () => deleteAgent(agent.id),
                  () => deleteModal.toggle(false)
                );
              }}
            >
              {t("deleteModal.submitButton.label")}
            </Button>
          }
        >
          <Text as="p" color="text-03">
            {richNodes(
              t.rich("deleteModal.confirmation.description", {
                name: agent.name,
                emphasis: (chunks) => (
                  <Text as="span" color="text-05">
                    {richNodes(chunks)}
                  </Text>
                ),
              })
            )}
          </Text>
        </ConfirmationModalLayout>
      </deleteModal.Provider>

      <featuredModal.Provider>
        <ConfirmationModalLayout
          icon={wasFeatured ? SvgStarOff : SvgStar}
          title={
            wasFeatured
              ? t("featuredModal.removeHeader.title", { name: agent.name })
              : t("featuredModal.addHeader.title", { name: agent.name })
          }
          onClose={isSubmitting ? undefined : () => featuredModal.toggle(false)}
          submit={
            <Button
              disabled={isSubmitting}
              onClick={() => {
                handleAction(
                  () => toggleAgentFeatured(agent.id, wasFeatured),
                  () => featuredModal.toggle(false)
                );
              }}
            >
              {wasFeatured
                ? t("featuredModal.unfeatureButton.label")
                : t("featuredModal.featureButton.label")}
            </Button>
          }
        >
          <div className="flex flex-col gap-2">
            <Text as="p" color="text-03">
              {wasFeatured
                ? t("featuredModal.removeBody.description", {
                    name: agent.name,
                  })
                : t("featuredModal.addBody.description")}
            </Text>
            <Text as="p" color="text-03">
              {t("modals.accessNote.description")}
            </Text>
          </div>
        </ConfirmationModalLayout>
      </featuredModal.Provider>

      <unlistModal.Provider>
        <ConfirmationModalLayout
          icon={SvgEyeOff}
          title={markdown(
            t("unlistModal.header.title", { name: escapeMarkdown(agent.name) })
          )}
          onClose={isSubmitting ? undefined : () => unlistModal.toggle(false)}
          submit={
            <Button
              disabled={isSubmitting}
              onClick={() => {
                handleAction(
                  () => toggleAgentListed(agent.id, agent.is_listed),
                  () => unlistModal.toggle(false)
                );
              }}
            >
              {t("unlistModal.submitButton.label")}
            </Button>
          }
        >
          <div className="flex flex-col gap-2">
            <Text as="p" color="text-03">
              {t("unlistModal.body.description")}
            </Text>
            <Text as="p" color="text-03">
              {t("modals.accessNote.description")}
            </Text>
          </div>
        </ConfirmationModalLayout>
      </unlistModal.Provider>
    </>
  );
}
