"use client";

import { useCallback, useState } from "react";
import { Button } from "@opal/components";
// TODO(@raunakab): migrate to Opal LineItemButton once it supports danger variant
import LineItem from "@/refresh-components/buttons/LineItem";
import { cn, markdown } from "@opal/utils";
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
import { Popover, PopoverMenu } from "@opal/components";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { useRouter } from "next/navigation";
import {
  deleteAgent,
  toggleAgentFeatured,
  toggleAgentListed,
} from "@/lib/agents/svc";
import type { Agent } from "@/lib/agents/types";
import type { Route } from "next";
import ShareAgentModal from "@/sections/modals/ShareAgentModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { useAgent } from "@/lib/agents/hooks";
import {
  updateAgentSharedStatus,
  updateAgentFeaturedStatus,
} from "@/lib/agents/svc";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";
import { useUser } from "@/providers/UserProvider";

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
  const router = useRouter();
  const { isAdmin, isCurator } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const canUpdateFeaturedStatus = isAdmin || isCurator;
  const { agent: fullAgent, refresh: refreshAgent } = useAgent(agent.id);
  const shareModal = useCreateModal();

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
      toast.success(`${agent.name} 已更新。`);
      close();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "发生错误");
    } finally {
      setIsSubmitting(false);
    }
  }

  const handleShare = useCallback(
    async (
      userIds: string[],
      groupIds: number[],
      isPublic: boolean,
      isFeatured: boolean,
      labelIds: number[]
    ) => {
      const shareError = await updateAgentSharedStatus(
        agent.id,
        userIds,
        groupIds,
        isPublic,
        businessTier,
        labelIds
      );

      if (shareError) {
        toast.error(`分享智能体失败：${shareError}`);
        return;
      }

      if (canUpdateFeaturedStatus) {
        const featuredError = await updateAgentFeaturedStatus(
          agent.id,
          isFeatured
        );
        if (featuredError) {
          toast.error(`更新精选状态失败：${featuredError}`);
          refreshAgent();
          return;
        }
      }

      refreshAgent();
      onMutate();
      shareModal.toggle(false);
    },
    [agent.id, businessTier, canUpdateFeaturedStatus, refreshAgent, onMutate]
  );

  return (
    <>
      <shareModal.Provider>
        <ShareAgentModal
          agentId={agent.id}
          userIds={fullAgent?.users?.map((u) => u.id) ?? []}
          groupIds={fullAgent?.groups ?? []}
          isPublic={fullAgent?.is_public ?? false}
          isFeatured={fullAgent?.is_featured ?? false}
          labelIds={fullAgent?.labels?.map((l) => l.id) ?? []}
          onShare={handleShare}
        />
      </shareModal.Provider>

      <div className="flex items-center gap-0.5">
        {/* TODO(@raunakab): abstract a more standardized way of doing this
            appear-on-hover animation. Making Hoverable more extensible
            (e.g. supporting table row groups) would let us use it here
            instead of raw Tailwind group-hover. */}
        {!agent.builtin_persona && (
          <div className="opacity-0 group-hover/row:opacity-100 transition-opacity">
            <Button
              prominence="tertiary"
              icon={SvgEdit}
              tooltip="编辑智能体"
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
            tooltip="重新上架智能体"
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
                agent.is_featured ? "取消精选" : "设为精选"
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
          <div
            className={cn(
              !popoverOpen &&
                "opacity-0 group-hover/row:opacity-100 transition-opacity"
            )}
          >
            <Popover.Trigger asChild>
              <Button prominence="tertiary" icon={SvgMoreHorizontal} />
            </Popover.Trigger>
          </div>
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
                  {agent.is_listed ? "下架智能体" : "上架智能体"}
                </LineItem>,
                <LineItem
                  key="share"
                  icon={SvgShare}
                  onClick={() => {
                    setPopoverOpen(false);
                    shareModal.toggle(true);
                  }}
                >
                  分享
                </LineItem>,
                businessTier ? (
                  <LineItem
                    key="stats"
                    icon={SvgBarChart}
                    onClick={() => {
                      setPopoverOpen(false);
                      router.push(`/ee/agents/stats/${agent.id}` as Route);
                    }}
                  >
                    统计
                  </LineItem>
                ) : undefined,
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
                    删除
                  </LineItem>
                ) : undefined,
              ]}
            </PopoverMenu>
          </Popover.Content>
        </Popover>
      </div>

      {deleteOpen && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="删除智能体"
          onClose={isSubmitting ? undefined : () => setDeleteOpen(false)}
          submit={
            <Button
              disabled={isSubmitting}
              variant="danger"
              onClick={() => {
                handleAction(
                  () => deleteAgent(agent.id),
                  () => setDeleteOpen(false)
                );
              }}
            >
              删除
            </Button>
          }
        >
          <Text as="p" text03>
            确定要删除{" "}
            <Text as="span" text05>
              {agent.name}
            </Text>
            吗？此操作无法撤销。
          </Text>
        </ConfirmationModalLayout>
      )}

      {featuredOpen && (
        <ConfirmationModalLayout
          icon={agent.is_featured ? SvgStarOff : SvgStar}
          title={
            agent.is_featured
              ? `将 ${agent.name} 移出精选`
              : `精选 ${agent.name}`
          }
          onClose={isSubmitting ? undefined : () => setFeaturedOpen(false)}
          submit={
            <Button
              disabled={isSubmitting}
              onClick={() => {
                handleAction(
                  () => toggleAgentFeatured(agent.id, agent.is_featured),
                  () => setFeaturedOpen(false)
                );
              }}
            >
              {agent.is_featured ? "取消精选" : "设为精选"}
            </Button>
          }
        >
          <div className="flex flex-col gap-2">
            <Text as="p" text03>
              {agent.is_featured
                ? `这会将 ${agent.name} 从探索智能体列表顶部的精选区域移除。新用户不会再在侧边栏看到它被置顶，但现有置顶不受影响。`
                : "精选智能体会显示在探索智能体列表顶部，并自动置顶到有访问权限的新用户侧边栏。可用于向组织重点推荐智能体。"}
            </Text>
            <Text as="p" text03>
              这不会改变谁可以访问此智能体。
            </Text>
          </div>
        </ConfirmationModalLayout>
      )}

      {unlistOpen && (
        <ConfirmationModalLayout
          icon={SvgEyeOff}
          title={markdown(`下架 *${agent.name}*`)}
          onClose={isSubmitting ? undefined : () => setUnlistOpen(false)}
          submit={
            <Button
              disabled={isSubmitting}
              onClick={() => {
                handleAction(
                  () => toggleAgentListed(agent.id, agent.is_listed),
                  () => setUnlistOpen(false)
                );
              }}
            >
              下架
            </Button>
          }
        >
          <div className="flex flex-col gap-2">
            <Text as="p" text03>
              已下架的智能体不会显示在探索智能体列表中，但仍可通过直接链接访问，
              也仍可被此前使用或置顶过它的用户访问。
            </Text>
            <Text as="p" text03>
              这不会改变谁可以访问此智能体。
            </Text>
          </div>
        </ConfirmationModalLayout>
      )}
    </>
  );
}
