import { useState } from "react";
import { ModalWrapper } from "@/components/modals/ModalWrapper";
import { Button, Callout, Divider, Text } from "@tremor/react";
import { Spinner } from "@/components/Spinner";
import { ChatSessionSharedStatus } from "../interfaces";
import { FiCopy, FiX } from "react-icons/fi";
import { CopyButton } from "@/components/CopyButton";

function buildShareLink(chatSessionId: number) {
  const baseUrl = `${window.location.protocol}//${window.location.host}`;
  return `${baseUrl}/chat/shared/${chatSessionId}`;
}

async function generateShareLink(chatSessionId: number) {
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

async function deleteShareLink(chatSessionId: number) {
  const response = await fetch(`/api/chat/chat-session/${chatSessionId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ sharing_status: "private" }),
  });

  return response.ok;
}

export function ShareChatSessionModal({
  chatSessionId,
  existingSharedStatus,
  onShare,
  onClose,
}: {
  chatSessionId: number;
  existingSharedStatus: ChatSessionSharedStatus;
  onShare?: (shared: boolean) => void;
  onClose: () => void;
}) {
  const [linkGenerating, setLinkGenerating] = useState(false);
  const [shareLink, setShareLink] = useState<string>(
    existingSharedStatus === ChatSessionSharedStatus.Public
      ? buildShareLink(chatSessionId)
      : ""
  );

  return (
    <ModalWrapper onClose={onClose} modalClassName="max-w-3xl">
      <>
        <div className="flex mb-4">
          <h2 className="text-2xl text-emphasis font-bold flex my-auto">
            Share link to Chat
          </h2>
        </div>

        {linkGenerating && <Spinner />}

        <div className="flex mt-2">
          {shareLink ? (
            <div>
              <Text>
                This chat session is currently shared. Anyone at your
                organization can view the message history using the following
                link:
              </Text>

              <div className="flex mt-2">
                <CopyButton content={shareLink} />
                <a
                  href={shareLink}
                  target="_blank"
                  className="underline text-link mt-1 ml-1 text-sm my-auto"
                >
                  {shareLink}
                </a>
              </div>

              <Divider />

              <Text className="mb-4">
                Click the button below to make the chat private again.
              </Text>

              <Button
                onClick={async () => {
                  setLinkGenerating(true);

                  const success = await deleteShareLink(chatSessionId);
                  if (success) {
                    setShareLink("");
                    onShare && onShare(false);
                  } else {
                    alert("Failed to delete share link");
                  }

                  setLinkGenerating(false);
                }}
                size="xs"
                color="red"
              >
                Delete Share Link
              </Button>
            </div>
          ) : (
            <div>
              <Callout title="Warning" color="yellow" className="mb-4">
                Ensure that all content in the chat is safe to share with the
                whole organization. The content of the retrieved documents will
                not be visible, but the names of cited documents as well as the
                AI and human messages will be visible.
              </Callout>

              <Button
                icon={FiCopy}
                onClick={async () => {
                  setLinkGenerating(true);

                  // NOTE: for "inescure" non-https setup, the `navigator.clipboard.writeText` may fail
                  // as the browser may not allow the clipboard to be accessed.
                  try {
                    const shareLink = await generateShareLink(chatSessionId);
                    if (!shareLink) {
                      alert("Failed to generate share link");
                    } else {
                      setShareLink(shareLink);
                      onShare && onShare(true);
                      navigator.clipboard.writeText(shareLink);
                    }
                  } catch (e) {
                    console.error(e);
                  }

                  setLinkGenerating(false);
                }}
                size="xs"
                color="green"
              >
                Generate and Copy Share Link
              </Button>
            </div>
          )}
        </div>
      </>
    </ModalWrapper>
  );
}
