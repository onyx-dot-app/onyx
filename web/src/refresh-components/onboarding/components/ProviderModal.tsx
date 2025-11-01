import React, { useRef } from "react";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import CoreModal from "@/refresh-components/modals/CoreModal";
import SvgLoader from "@/icons/loader";

interface ProviderModalProps {
  // Modal sizes
  sm?: boolean;
  xs?: boolean;

  // Modal configurations
  clickOutsideToClose?: boolean;

  // Base modal props
  id: ModalIds;
  icon?: React.FunctionComponent<SvgProps>;
  startAdornment?: React.ReactNode;
  title: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;

  // Footer props
  onSubmit?: () => void;
  submitDisabled?: boolean;
  isSubmitting?: boolean;
  submitLabel?: string;
  cancelLabel?: string;
}

export default function ProviderModal({
  sm,
  xs,

  clickOutsideToClose = true,

  id,
  icon: Icon,
  startAdornment,
  title,
  description,
  children,
  onSubmit,
  submitDisabled = false,
  isSubmitting = false,
  submitLabel = "Connect",
  cancelLabel = "Cancel",
  className,
}: ProviderModalProps) {
  const { isOpen, toggleModal } = useChatModal();
  const insideModal = useRef(false);

  const SpinningLoader: React.FunctionComponent<SvgProps> = (props) => (
    <SvgLoader
      {...props}
      className={`${
        props.className ?? ""
      } h-3 w-3 stroke-text-inverted-04 animate-spin`}
    />
  );

  if (!isOpen(id)) return null;

  return (
    <CoreModal
      className={cn(
        "w-[80dvw] h-fit max-h-[calc(100dvh-9rem)]",
        sm && "max-w-[60rem]",
        xs && "max-w-[32rem]",
        className
      )}
      onClickOutside={
        clickOutsideToClose
          ? () => {
              if (insideModal.current) return;
              toggleModal(id, false);
            }
          : undefined
      }
    >
      <div className="flex flex-col h-full max-h-[calc(100dvh-9rem)]">
        <div className="flex flex-col gap-2 p-4">
          <div className="flex flex-row items-center justify-between">
            {Icon ? (
              <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
            ) : (
              startAdornment
            )}
            <div data-testid="Modal/close-modal">
              <IconButton
                icon={SvgX}
                internal
                onClick={() => toggleModal(id, false)}
              />
            </div>
          </div>
          <Text headingH3>{title}</Text>
          {description && (
            <Text secondaryBody text02>
              {description}
            </Text>
          )}
        </div>
        <div className="flex-1 overflow-scroll">{children}</div>
        {onSubmit && (
          <div className="sticky bottom-0">
            <div className="flex justify-end gap-2 w-full p-4">
              <Button
                type="button"
                secondary
                onClick={() => toggleModal(id, false)}
              >
                {cancelLabel}
              </Button>
              <Button
                type="button"
                onClick={onSubmit}
                disabled={submitDisabled || isSubmitting}
                leftIcon={isSubmitting ? SpinningLoader : undefined}
              >
                {submitLabel}
              </Button>
            </div>
          </div>
        )}
      </div>
    </CoreModal>
  );
}
