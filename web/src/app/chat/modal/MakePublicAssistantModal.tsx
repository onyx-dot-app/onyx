import { ModalWrapper } from "@/components/modals/ModalWrapper";
import { Button, Divider, Text } from "@tremor/react";

export function MakePublicAssistantModal({
  isPublic,
  onShare,
  onClose,
}: {
  isPublic: boolean;
  onShare: (shared: boolean) => void;
  onClose: () => void;
}) {
  return (
    <ModalWrapper onClose={onClose} modalClassName="max-w-3xl">
      <div className="space-y-6">
        <h2 className="text-2xl font-bold text-emphasis">
          {isPublic ? "Public Assistant" : "Make Assistant Public"}
        </h2>

        <Text>
          This assistant is currently{" "}
          <span className="font-semibold">
            {isPublic ? "public" : "private"}
          </span>
          .
          {isPublic
            ? " Anyone can currently access this assistant."
            : " Only you can access this assistant."}
        </Text>

        <Divider />

        {isPublic ? (
          <div className="space-y-4">
            <Text>
              To restrict access to this assistant, you can make it private
              again.
            </Text>
            <Button
              onClick={async () => {
                await onShare?.(false);
                onClose();
              }}
              size="sm"
              color="red"
            >
              Make Assistant Private
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <Text>
              Making this assistant public will allow anyone with the link to
              view and use it. Ensure that all content and capabilities of the
              assistant are safe to share.
            </Text>
            <Button
              onClick={async () => {
                await onShare?.(true);
                onClose();
              }}
              size="sm"
              color="green"
            >
              Make Assistant Public
            </Button>
          </div>
        )}
      </div>
    </ModalWrapper>
  );
}
