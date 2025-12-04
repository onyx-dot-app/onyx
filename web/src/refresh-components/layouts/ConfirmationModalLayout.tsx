import React from "react";
import { IconProps } from "@/icons";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import DefaultModalLayout from "./DefaultModalLayout";
import { useModalClose } from "../contexts/ModalContext";

export interface ConfirmationModalProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
  onClose?: () => void;
}

export default function ConfirmationModalLayout({
  icon,
  title,
  children,

  submit,
  hideCancel,
  onClose: externalOnClose,
}: ConfirmationModalProps) {
  const onClose = useModalClose(externalOnClose);

  return (
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
          <Button secondary onClick={onClose} type="button">
            Cancel
          </Button>
        )}
        {submit}
      </div>
    </DefaultModalLayout>
  );
}
