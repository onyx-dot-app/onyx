"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { ChatSession, ChatSessionSharedStatus } from "@/app/app/interfaces";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { toast } from "@/hooks/useToast";
import { structureValue } from "@/lib/llm/utils";
import { LlmDescriptor, useLlmManager } from "@/lib/hooks";
import { useCurrentAgent } from "@/hooks/useAgents";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { copyAll } from "@/app/app/message/copyingUtils";
import { Section } from "@/layouts/general-layouts";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Separator from "@/refresh-components/Separator";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import Message from "@/refresh-components/messages/Message";
import Text from "@/refresh-components/texts/Text";
import { SvgCopy, SvgLink, SvgShare, SvgUsers } from "@opal/icons";
import SvgCheck from "@opal/icons/check";
import SvgLock from "@opal/icons/lock";

import type { IconProps } from "@opal/types";

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

async function generateSeedLink(
  message?: string,
  assistantId?: number,
  modelOverride?: LlmDescriptor
) {
  const baseUrl = `${window.location.protocol}//${window.location.host}`;
  const model = modelOverride
    ? structureValue(
        modelOverride.name,
        modelOverride.provider,
        modelOverride.modelName
      )
    : null;
  return `${baseUrl}/app${
    message
      ? `?${SEARCH_PARAM_NAMES.USER_PROMPT}=${encodeURIComponent(message)}`
      : ""
  }${
    assistantId
      ? `${message ? "&" : "?"}${SEARCH_PARAM_NAMES.PERSONA_ID}=${assistantId}`
      : ""
  }${
    model
      ? `${message || assistantId ? "&" : "?"}${
          SEARCH_PARAM_NAMES.STRUCTURED_MODEL
        }=${encodeURIComponent(model)}`
      : ""
  }${message ? `&${SEARCH_PARAM_NAMES.SEND_ON_LOAD}=true` : ""}`;
}

interface PrivacyOptionProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  selected: boolean;
  onClick: () => void;
}

function PrivacyOption({
  icon: Icon,
  title,
  description,
  selected,
  onClick,
}: PrivacyOptionProps) {
  return (
    <div
      className={cn(
        "p-1.5 rounded-08 cursor-pointer ",
        selected ? "bg-background-tint-00" : "bg-transparent",
        "hover:bg-background-tint-02"
      )}
      onClick={onClick}
    >
      <div className="flex flex-row gap-1 items-center">
        <div className="flex w-5 p-[2px] self-stretch justify-center">
          <Icon
            size={16}
            className={cn(selected ? "stroke-text-05" : "stroke-text-03")}
          />
        </div>
        <div className="flex flex-col flex-1 px-0.5">
          <Text mainUiBody text05={selected} text03={!selected}>
            {title}
          </Text>
          <Text secondaryBody text03>
            {description}
          </Text>
        </div>
        {selected && (
          <div className="flex w-5 self-stretch justify-center">
            <SvgCheck size={16} className="stroke-action-link-05" />
          </div>
        )}
      </div>
    </div>
  );
}

interface ShareChatSessionModalProps {
  chatSession: ChatSession;
  onClose: () => void;
  refreshChatSessions: () => void;
}

export default function ShareChatSessionModal({
  chatSession,
  onClose,
  refreshChatSessions,
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
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  const currentAgent = useCurrentAgent();
  const searchParams = useSearchParams();
  const message = searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) || "";
  const llmManager = useLlmManager(chatSession, currentAgent || undefined);
  const updateCurrentChatSessionSharedStatus = useChatSessionStore(
    (state) => state.updateCurrentChatSessionSharedStatus
  );

  const wantsPublic = selectedPrivacy === "public";

  const isShared = shareLink && selectedPrivacy === "public";

  let submitButtonText = "Done";
  if (wantsPublic && !isCurrentlyPublic && !shareLink) {
    submitButtonText = "Create Share Link";
  } else if (!wantsPublic && isCurrentlyPublic) {
    submitButtonText = "Make Private";
  } else if (isShared) {
    submitButtonText = "Copy Link";
  }

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
          toast.success("Share link copied to clipboard!");
        } else {
          toast.error("Failed to generate share link");
        }
      } else if (!wantsPublic && isCurrentlyPublic) {
        const success = await deleteShareLink(chatSession.id);
        if (success) {
          setShareLink("");
          updateCurrentChatSessionSharedStatus(ChatSessionSharedStatus.Private);
          await refreshChatSessions();
          toast.success("Chat is now private");
          onClose();
        } else {
          toast.error("Failed to make chat private");
        }
      } else if (wantsPublic && shareLink) {
        copyAll(shareLink);
        toast.success("Share link copied to clipboard!");
      } else {
        onClose();
      }
    } catch (e) {
      console.error(e);
      toast.error("An error occurred");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgShare}
          title={isShared ? "Chat shared" : "Share this chat"}
          description="All existing and future messages in this chat will be shared."
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <Section
            justifyContent="start"
            alignItems="stretch"
            gap={1}
            height="auto"
          >
            <Section
              justifyContent="start"
              alignItems="stretch"
              height="auto"
              gap={0.12}
            >
              <PrivacyOption
                icon={SvgLock}
                title="Private"
                description="Only you have access to this chat."
                selected={selectedPrivacy === "private"}
                onClick={() => setSelectedPrivacy("private")}
              />
              <PrivacyOption
                icon={SvgUsers}
                title="Your Organization"
                description="Anyone in your organization can view this chat."
                selected={selectedPrivacy === "public"}
                onClick={() => setSelectedPrivacy("public")}
              />
            </Section>

            {isShared && (
              <InputTypeIn
                readOnly
                value={shareLink}
                rightSection={
                  <CopyIconButton
                    getCopyText={() => shareLink}
                    tooltip="Copy link"
                    size="sm"
                  />
                }
              />
            )}
          </Section>

          <Separator className="py-0" />

          <Section
            justifyContent="start"
            alignItems="stretch"
            gap={0.5}
            height="auto"
          >
            <AdvancedOptionsToggle
              showAdvancedOptions={showAdvancedOptions}
              setShowAdvancedOptions={setShowAdvancedOptions}
              title="Advanced Options"
            />

            {showAdvancedOptions && (
              <Section
                justifyContent="start"
                alignItems="stretch"
                gap={0.5}
                height="auto"
              >
                <Message
                  static
                  info
                  medium
                  className="w-full"
                  text="Seed New Chat"
                  description="Generate a link to a new chat session with the same settings as this chat (including the assistant and model)."
                  close={false}
                />
                <Button
                  leftIcon={SvgCopy}
                  onClick={async () => {
                    try {
                      const seedLink = await generateSeedLink(
                        message,
                        currentAgent?.id,
                        llmManager.currentLlm
                      );
                      if (!seedLink) {
                        toast.error("Failed to generate seed link");
                      } else {
                        copyAll(seedLink);
                        toast.success("Link copied to clipboard!");
                      }
                    } catch (e) {
                      console.error(e);
                      toast.error("Failed to generate or copy link.");
                    }
                  }}
                  secondary
                >
                  Generate and Copy Seed Link
                </Button>
              </Section>
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          {!isShared && (
            <Button secondary onClick={onClose}>
              Cancel
            </Button>
          )}
          <Button
            onClick={handleSubmit}
            disabled={isLoading}
            leftIcon={isShared ? SvgLink : undefined}
            className={isShared ? "w-full" : undefined}
          >
            {submitButtonText}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
