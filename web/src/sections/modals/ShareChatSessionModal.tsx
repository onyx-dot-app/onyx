"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChatSession, ChatSessionSharedStatus } from "@/app/app/interfaces";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { copyAll } from "@/app/app/message/copyingUtils";
import { Section } from "@/layouts/general-layouts";
import { Modal } from "@opal/components";
import { Button, CopyButton, InputTypeIn, SelectCard } from "@opal/components";
import { ContentAction, toast } from "@opal/layouts";
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
      padding={2}
      rounding={2}
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
        padding={0}
        color="interactive"
        rightChildren={
          selected ? (
            <SvgCheck
              size={16}
              className="shrink-0 stroke-action-selection-05"
            />
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
  const t = useTranslations("chat.modals.share");
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
    submitButtonText = t("copyLinkButton.label");
  } else if (isCurrentlyPublic && !wantsPublic) {
    submitButtonText = t("makePrivateButton.label");
  } else {
    submitButtonText = t("createLinkButton.label");
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
          toast.success(t("linkCopiedToast.message"));
        } else {
          toast.error(t("generateLinkErrorToast.message"));
        }
      } else if (!wantsPublic && isCurrentlyPublic) {
        const success = await deleteShareLink(chatSession.id);
        if (success) {
          setShareLink("");
          updateCurrentChatSessionSharedStatus(ChatSessionSharedStatus.Private);
          await refreshChatSessions();
          toast.success(t("nowPrivateToast.message"));
          onClose();
        } else {
          toast.error(t("makePrivateErrorToast.message"));
        }
      } else if (wantsPublic && shareLink) {
        copyAll(shareLink);
        toast.success(t("linkCopiedToast.message"));
      } else {
        onClose();
      }
    } catch (e) {
      console.error(e);
      toast.error(t("genericErrorToast.message"));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgShare}
          title={isShared ? t("header.sharedTitle") : t("header.title")}
          description={t("header.description")}
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <Section
            justifyContent="start"
            alignItems="stretch"
            height="auto"
            gap={1}
          >
            <PrivacyOption
              icon={SvgLock}
              title={t("privateOption.title")}
              description={t("privateOption.description")}
              selected={selectedPrivacy === "private"}
              onClick={() => setSelectedPrivacy("private")}
              ariaLabel="share-modal-option-private"
            />
            <PrivacyOption
              icon={SvgUsers}
              title={t("organizationOption.title")}
              description={t("organizationOption.description")}
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
                  tooltip={t("linkInput.copyTooltip")}
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
              {t("cancelButton.label")}
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
