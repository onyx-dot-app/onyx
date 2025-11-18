import React from "react";
import Text from "@/refresh-components/texts/Text";

import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import { Modal } from "@/refresh-components/Modal";
import SvgLoader from "@/icons/loader";

interface ProviderModalProps {
  // Modal sizes
  sm?: boolean;
  xs?: boolean;

  // Modal configurations
  clickOutsideToClose?: boolean;

  // Base modal props
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
  clickOutsideToClose = true,

  open,
  onOpenChange,
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
}: ProviderModalProps) {
  const SpinningLoader: React.FunctionComponent<SvgProps> = (props) => (
    <SvgLoader
      {...props}
      className={`${
        props.className ?? ""
      } h-3 w-3 stroke-text-inverted-04 animate-spin`}
    />
  );

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      onOpenChange(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={handleOpenChange}>
      <Modal.Content
        size="small"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => {
          if (!clickOutsideToClose) {
            e.preventDefault();
          }
        }}
      >
        <Modal.CloseButton />

        <Modal.Header className="flex flex-col gap-2 p-4">
          {Icon ? (
            <Modal.Icon icon={Icon} />
          ) : startAdornment ? (
            startAdornment
          ) : null}
          <Modal.Title>{title}</Modal.Title>
          {description && <Modal.Description>{description}</Modal.Description>}
        </Modal.Header>

        <Modal.Body className="flex-1 overflow-y-auto">{children}</Modal.Body>

        {onSubmit && (
          <Modal.Footer className="flex justify-end gap-2 p-4">
            <Button type="button" secondary onClick={() => onOpenChange(false)}>
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
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}
