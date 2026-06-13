"use client";

import { useState } from "react";
import { ChatSession, ChatSessionSharedStatus } from "@/app/app/interfaces";
import { toast } from "@/hooks/useToast";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { copyAll } from "@/app/app/message/copyingUtils";
import { Section } from "@/layouts/general-layouts";
import Modal from "@/refresh-components/Modal";
import { Button, CopyButton, InputTypeIn, SelectCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgLink, SvgShare, SvgUsers } from "@opal/icons";
import SvgCheck from "@opal/icons/check";
import SvgLock from "@opal/icons/lock";

import type { IconProps } from "@opal/types";
import useChatSessions from "@/hooks/useChatSessions";

function buildShareLink(chatSessionId: string) {
  const baseUrl = `${window.location.protocol}//${window.location.host}`;
  return `${baseUrl}/app/shared/${chatSessionId}`;
}

async function generateShareLink(chatSessionId: string) {
  const response = await fetch(`/api/chat/chat-session/${chatSessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sharing_status: "public" }),
  });

  if (response.ok) {
    return buildShareLink(chatSessionId);
  }
  return null;
}

async function deleteShareLink(chatSessionId: string) {
  const response = await fetch(`/api/chat/chat-session/${chatSessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sharing_status: "private" }),
  });

  return response.ok;
}

interface PrivacyOptionProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  selected: boolean;
  onClick: () => void;
  ariaLabel?: string;
}

function PrivacyOption({
  icon: Icon,
  title,
  description,
  selected,
  onClick,
  ariaLabel,
}: PrivacyOptionProps) {
  return (
    <SelectCard
      state={selected ? "filled" : "empty"}
      padding="sm"
      rounding="sm"
      border="none"
      onClick={onClick}
      aria-label={ariaLabel}
    >
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        icon={Icon}
        title={title}
        description={description}
        padding="fit"
        color="interactive"
        rightChildren={
          selected ? (
            <SvgCheck size={16} className="shrink-0 stroke-action-link-05" />
          ) : undefined
        }
      />
    </SelectCard>
  );
}

interface ShareChatSessionModalProps {
  chatSession: ChatSession;
  onClose: () => void;
}

export default function ShareChatSessionModal({
  chatSession,
  onClose,
}: ShareChatSessionModalProps) {
  const isCurrentlyPublic =
    chatSession.shared_status === ChatSessionSharedStatus.Public;

  const [selectedPrivacy, setSelectedPrivacy] = useState<"private" | "public">(
    isCurrentlyPublic ? "public" : "private"
  );
  const [shareLink, setShareLink] = useState<string>(
    isCurrentlyPublic ? buildShareLink(chatSession.id) : ""
  );
  const [isLoading, setIsLoading] = useState(false);
  const updateCurrentChatSessionSharedStatus = useChatSessionStore(
    (state) => state.updateCurrentChatSessionSharedStatus
  );
  const { refreshChatSessions } = useChatSessions();

  const wantsPublic = selectedPrivacy === "public";

  const isShared = shareLink && selectedPrivacy === "public";

  let submitButtonText: string;
  if (isShared) {
    submitButtonText = "复制链接";
  } else if (isCurrentlyPublic && !wantsPublic) {
    submitButtonText = "设为私密";
  } else {
    submitButtonText = "创建分享链接";
  }

  const submitDisabled = isLoading || (!isCurrentlyPublic && !wantsPublic);

  async function handleSubmit() {
    setIsLoading(true);
    try {
      if (wantsPublic && !isCurrentlyPublic && !shareLink) {
        const link = await generateShareLink(chatSession.id);
        if (link) {
          setShareLink(link);
          updateCurrentChatSessionSharedStatus(ChatSessionSharedStatus.Public);
          await refreshChatSessions();
          copyAll(link);
          toast.success("分享链接已复制到剪贴板！");
        } else {
          toast.error("生成分享链接失败");
        }
      } else if (!wantsPublic && isCurrentlyPublic) {
        const success = await deleteShareLink(chatSession.id);
        if (success) {
          setShareLink("");
          updateCurrentChatSessionSharedStatus(ChatSessionSharedStatus.Private);
          await refreshChatSessions();
          toast.success("聊天已设为私密");
          onClose();
        } else {
          toast.error("设为私密失败");
        }
      } else if (wantsPublic && shareLink) {
        copyAll(shareLink);
        toast.success("分享链接已复制到剪贴板！");
      } else {
        onClose();
      }
    } catch (e) {
      console.error(e);
      toast.error("发生错误");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgShare}
          title={isShared ? "聊天已分享" : "分享此聊天"}
          description="此聊天中现有和未来的所有消息都会被分享。"
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <Section
            justifyContent="start"
            alignItems="stretch"
            height="auto"
            gap={0.25}
          >
            <PrivacyOption
              icon={SvgLock}
              title="私密"
              description="只有你可以访问此聊天。"
              selected={selectedPrivacy === "private"}
              onClick={() => setSelectedPrivacy("private")}
              ariaLabel="share-modal-option-private"
            />
            <PrivacyOption
              icon={SvgUsers}
              title="你的组织"
              description="你组织内的任何人都可以查看此聊天。"
              selected={selectedPrivacy === "public"}
              onClick={() => setSelectedPrivacy("public")}
              ariaLabel="share-modal-option-public"
            />
          </Section>

          {isShared && (
            <InputTypeIn
              aria-label="share-modal-link-input"
              variant="readOnly"
              value={shareLink}
              rightChildren={
                <CopyButton
                  getCopyText={() => shareLink}
                  tooltip="复制链接"
                  size="sm"
                  aria-label="share-modal-copy-link"
                />
              }
            />
          )}
        </Modal.Body>
        <Modal.Footer>
          {!isShared && (
            <Button
              prominence="secondary"
              onClick={onClose}
              aria-label="share-modal-cancel"
            >
              取消
            </Button>
          )}
          <Button
            disabled={submitDisabled}
            onClick={handleSubmit}
            icon={isShared ? SvgLink : undefined}
            width={isShared ? "full" : undefined}
            aria-label="share-modal-submit"
          >
            {submitButtonText}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
