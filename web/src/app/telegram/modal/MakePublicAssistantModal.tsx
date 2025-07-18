import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
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
          {isPublic
            ? i18n.t(k.PUBLIC_ASSISTANT)
            : i18n.t(k.MAKE_ASSISTANT_PUBLIC)}
        </h2>

        <Text>
          {i18n.t(k.THIS_ASSISTANT_IS_CURRENTLY)}{" "}
          <span className="font-semibold">
            {isPublic ? i18n.t(k.PUBLIC1) : i18n.t(k.PRIVATE)}
          </span>
          {i18n.t(k._8)}
          {isPublic
            ? i18n.t(k.ANYONE_CAN_CURRENTLY_ACCESS_TH)
            : i18n.t(k.ONLY_YOU_CAN_ACCESS_THIS_ASSIS)}
        </Text>

        <Separator />

        {isPublic ? (
          <div className="space-y-4">
            <Text>{i18n.t(k.TO_RESTRICT_ACCESS_TO_THIS_ASS1)}</Text>
            <Button
              onClick={async () => {
                await onShare?.(false);
                onClose();
              }}
              size="sm"
              variant="destructive"
            >
              {i18n.t(k.MAKE_ASSISTANT_PRIVATE)}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <Text>{i18n.t(k.MAKING_THIS_ASSISTANT_PUBLIC_W1)}</Text>
            <Button
              onClick={async () => {
                await onShare?.(true);
                onClose();
              }}
              size="sm"
              variant="submit"
            >
              {i18n.t(k.MAKE_ASSISTANT_PUBLIC)}
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}
