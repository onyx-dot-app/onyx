import Button from "@/refresh-components/buttons/Button";
import Modal, { ModalProps } from "@/refresh-components/modals/Modal";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { useModal } from "@/refresh-components/contexts/ModalContext";

interface ProviderModalProps extends ModalProps {
  // Footer props
  onSubmit?: () => void;
  submitDisabled?: boolean;
  isSubmitting?: boolean;
  submitLabel?: string;
  cancelLabel?: string;
}

export default function ProviderModal({
  icon,
  title,
  description,
  children,
  onSubmit,
  submitDisabled = false,
  isSubmitting = false,
  submitLabel = "Connect",
  cancelLabel = "Cancel",
}: ProviderModalProps) {
  const modal = useModal();

  return (
    <Modal icon={icon} title={title} description={description}>
      <div className="flex flex-col h-full max-h-[calc(100dvh-9rem)]">
        <div className="flex-1 overflow-scroll">{children}</div>
        {onSubmit && (
          <div className="sticky bottom-0">
            <div className="flex justify-end gap-2 w-full p-4">
              <Button
                type="button"
                secondary
                onClick={() => modal.toggle(false)}
              >
                {cancelLabel}
              </Button>
              <Button
                type="button"
                onClick={onSubmit}
                disabled={submitDisabled || isSubmitting}
                leftIcon={isSubmitting ? SimpleLoader : undefined}
              >
                {submitLabel}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
