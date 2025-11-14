import React from "react";
import { SvgProps } from "@/icons";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import SimpleModal from "@/refresh-components/SimpleModal";
import { useEscape } from "@/hooks/useKeyPress";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import DefaultModalLayout from "./DefaultModalLayout";

export interface ConfirmationModalProps {
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose: () => void;
}

export default function ConfirmationModalLayout({
  icon,
  title,
  children,

  submit,
  hideCancel,
  onClose,
}: ConfirmationModalProps) {
  return (
    <SimpleModal onClose={onClose}>
      <DefaultModalLayout icon={icon} title={title} onClose={onClose} mini>
        <div className="p-4">
          {typeof children === "string" ? (
            <Text text03>{children}</Text>
          ) : (
            children
          )}
        </div>
        <div className="flex flex-row w-full items-center justify-end p-4 gap-2">
          {!hideCancel && (
            <Button secondary onClick={onClose}>
              Cancel
            </Button>
          )}
          {submit}
        </div>
      </DefaultModalLayout>
    </SimpleModal>
  );
}
