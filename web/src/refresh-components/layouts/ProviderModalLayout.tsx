import Button from "@/refresh-components/buttons/Button";
import DefaultModalLayout, {
  ModalProps,
} from "@/refresh-components/layouts/DefaultModalLayout";
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

export default function ProviderModalLayout({
  onSubmit,
  submitDisabled = false,
  isSubmitting = false,
  submitLabel = "Connect",
  cancelLabel = "Cancel",

  children,
  ...rest
}: ProviderModalProps) {
  const modal = useModal();

  return (
    <DefaultModalLayout {...rest}>
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
    </DefaultModalLayout>
  );
}
