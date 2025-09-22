import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";

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
    <Modal onOutsideClick={onClose} width="max-w-3xl">
      <div className="space-y-6">
        <h2 className="text-2xl font-bold text-text-darker">
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

        <Separator />

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
              variant="destructive"
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
              variant="submit"
            >
              Make Assistant Public
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}
