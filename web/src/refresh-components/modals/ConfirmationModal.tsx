import React from "react";
import { SvgProps } from "@/icons";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import CoreModal from "@/refresh-components/modals/CoreModal";
import { useEscape } from "@/hooks/useKeyPress";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";

interface ConfirmationModalProps {
  escapeToClose?: boolean;
  clickOutsideToClose?: boolean;

  icon: React.FunctionComponent<SvgProps>;
  title: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose: () => void;
}

export default function ConfirmationModal({
  escapeToClose = true,
  clickOutsideToClose = true,

  icon: Icon,
  title,
  children,

  submit,
  hideCancel,
  onClose,
}: ConfirmationModalProps) {
  useEscape(onClose, escapeToClose);

  return (
    <CoreModal
      className="z-10 w-[27rem] rounded-16 border flex flex-col bg-background-tint-00"
      onClickOutside={clickOutsideToClose ? onClose : undefined}
    >
      <div className="flex flex-col items-center justify-center p-spacing-paragraph gap-spacing-inline">
        <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
          <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          <IconButton icon={SvgX} internal onClick={onClose} />
        </div>
        <Text headingH3 text04 className="w-full text-left">
          {title}
        </Text>
      </div>
      <div className="p-spacing-paragraph">
        {typeof children === "string" ? (
          <Text text03>{children}</Text>
        ) : (
          children
        )}
      </div>
      <div className="flex flex-row w-full items-center justify-end p-spacing-paragraph gap-spacing-interline">
        {!hideCancel && (
          <Button secondary onClick={onClose}>
            Cancel
          </Button>
        )}
        {submit}
      </div>
    </CoreModal>
  );
}
