import { useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import { Callout } from "@/components/ui/callout";
import Text from "@/components/ui/text";
import { ChatSession, ChatSessionSharedStatus } from "@/app/chat/interfaces";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { usePopup } from "@/components/admin/connectors/Popup";
import { structureValue } from "@/lib/llm/utils";
import { LlmDescriptor, useLlmManager } from "@/lib/hooks";
import { Separator } from "@/components/ui/separator";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { cn } from "@/lib/utils";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { useSearchParams } from "next/navigation";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { useChatSessionStore } from "@/app/chat/stores/useChatSessionStore";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import SvgShare from "@/icons/share";
import SvgCopy from "@/icons/copy";
import IconButton from "@/refresh-components/buttons/IconButton";
import { copyAll } from "@/app/chat/message/copyingUtils";

function buildShareLink(chatSessionId: string) {
  const baseUrl = `${window.location.protocol}//${window.location.host}`;
  return `${baseUrl}/chat/shared/${chatSessionId}`;
}

async function generateShareLink(chatSessionId: string) {
  const response = await fetch(`/api/chat/chat-session/${chatSessionId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ sharing_status: "public" }),
  });

  if (response.ok) {
    return buildShareLink(chatSessionId);
  }
  return null;
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
  return `${baseUrl}/chat${
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

async function deleteShareLink(chatSessionId: string) {
  const response = await fetch(`/api/chat/chat-session/${chatSessionId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ sharing_status: "private" }),
  });

  return response.ok;
}

interface ShareChatSessionModalProps {
  chatSession: ChatSession;
  onClose: () => void;
}

export default function ShareChatSessionModal({
  chatSession,
  onClose,
}: ShareChatSessionModalProps) {
  const [shareLink, setShareLink] = useState<string>(
    chatSession.shared_status === ChatSessionSharedStatus.Public
      ? buildShareLink(chatSession.id)
      : ""
  );
  const { popup, setPopup } = usePopup();
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const { currentAgent } = useAgentsContext();
  const searchParams = useSearchParams();
  const message = searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) || "";
  const { llmProviders } = useChatContext();
  const llmManager = useLlmManager(
    llmProviders,
    chatSession,
    currentAgent || undefined
  );
  const updateCurrentChatSessionSharedStatus = useChatSessionStore(
    (state) => state.updateCurrentChatSessionSharedStatus
  );

  return (
    <>
      {popup}

      <ConfirmationModal
        icon={SvgShare}
        title="Share Chat"
        onClose={onClose}
        submit={<Button>Share</Button>}
      >
        {shareLink ? (
          <div>
            <Text>
              This chat session is currently shared. Anyone in your team can
              view the message history using the following link:
            </Text>

            <div className={cn("flex mt-2")}>
              {/* <CopyButton content={shareLink} /> */}
              <IconButton
                icon={SvgCopy}
                onClick={() => copyAll(shareLink)}
                secondary
              />
              <a
                href={shareLink}
                target="_blank"
                className={cn(
                  "underline mt-1 ml-1 text-sm my-auto",
                  "text-action-link-05"
                )}
                rel="noreferrer"
              >
                {shareLink}
              </a>
            </div>

            <Separator />

            <Text className={cn("mb-4")}>
              Click the button below to make the chat private again.
            </Text>

            <Button
              onClick={async () => {
                const success = await deleteShareLink(chatSession.id);
                if (success) {
                  setShareLink("");
                  updateCurrentChatSessionSharedStatus(
                    ChatSessionSharedStatus.Private
                  );
                } else {
                  alert("Failed to delete share link");
                }
              }}
              danger
            >
              Delete Share Link
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-spacing-interline">
            <Callout type="warning" title="Warning">
              Please make sure that all content in this chat is safe to share
              with the whole team.
            </Callout>
            <Button
              leftIcon={SvgCopy}
              onClick={async () => {
                // NOTE: for "insecure" non-https setup, the `navigator.clipboard.writeText` may fail
                // as the browser may not allow the clipboard to be accessed.
                try {
                  const shareLink = await generateShareLink(chatSession.id);
                  if (!shareLink) {
                    alert("Failed to generate share link");
                  } else {
                    setShareLink(shareLink);
                    updateCurrentChatSessionSharedStatus(
                      ChatSessionSharedStatus.Public
                    );
                    copyAll(shareLink);
                  }
                } catch (e) {
                  console.error(e);
                }
              }}
              secondary
            >
              Generate and Copy Share Link
            </Button>
          </div>
        )}

        <Separator className={cn("my-4")} />

        <AdvancedOptionsToggle
          showAdvancedOptions={showAdvancedOptions}
          setShowAdvancedOptions={setShowAdvancedOptions}
          title="Advanced Options"
        />

        {showAdvancedOptions && (
          <div className="flex flex-col gap-spacing-interline">
            <Callout type="notice" title="Seed New Chat">
              Generate a link to a new chat session with the same settings as
              this chat (including the assistant and model).
            </Callout>
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
                    setPopup({
                      message: "Failed to generate seed link",
                      type: "error",
                    });
                  } else {
                    navigator.clipboard.writeText(seedLink);
                    copyAll(seedLink);
                    setPopup({
                      message: "Link copied to clipboard!",
                      type: "success",
                    });
                  }
                } catch (e) {
                  console.error(e);
                  alert("Failed to generate or copy link.");
                }
              }}
              secondary
            >
              Generate and Copy Seed Link
            </Button>
          </div>
        )}
      </ConfirmationModal>
    </>
  );
}
