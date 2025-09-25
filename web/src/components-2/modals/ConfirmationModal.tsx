import React from "react";
import { SvgProps } from "@/icons";
import Text from "@/components-2/Text";
import SvgX from "@/icons/x";
import CoreModal from "@/components-2/modals/CoreModal";
import { useEscape } from "@/hooks/useEscape";

interface ConfirmationModalProps {
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  escapeToClose?: boolean;
  clickOutsideToClose?: boolean;
  onClose: () => void;
  description?: React.ReactNode;
  children?: React.ReactNode;
}

export default function ConfirmationModal({
  icon: Icon,
  title,
  escapeToClose = true,
  clickOutsideToClose = true,
  onClose,
  description,

  children,
}: ConfirmationModalProps) {
  useEscape(onClose, escapeToClose);

  return (
    <CoreModal
      className="z-10 w-[27rem] rounded-16 border flex flex-col bg-background-tint-00"
      onClickOutside={clickOutsideToClose ? () => onClose?.() : undefined}
    >
      <div className="flex flex-col items-center justify-center p-spacing-paragraph gap-spacing-inline">
        <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
          <Icon className="w-[1.2rem] h-[1.2rem] stroke-text-04" />
          <SvgX
            className="stroke-text-03 w-[1.2rem] h-[1.2rem] hover:stroke-text-02"
            onClick={onClose}
          />
        </div>
        <Text headingH3 text04 className="w-full text-left">
          {title}
        </Text>
      </div>
      {description && (
        <div className="p-spacing-paragraph">
          {typeof description === "string" ? (
            <Text text03>{description}</Text>
          ) : (
            description
          )}
        </div>
      )}
      {children && <div className="p-spacing-paragraph">{children}</div>}
    </CoreModal>
  );
}
