import React from "react";
import { SvgProps } from "@/icons";
import Text from "@/refresh-components/Text";
import SvgX from "@/icons/x";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import { useModal } from "@/refresh-components/contexts/ModalContext";

interface ConfirmationModalContentProps {
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  children?: React.ReactNode;

  submit: React.ReactNode;
  hideCancel?: boolean;
}

export default function ConfirmationModalContent({
  icon: Icon,
  title,
  children,

  submit,
  hideCancel,
}: ConfirmationModalContentProps) {
  const { toggle } = useModal();

  return (
    <>
      <div className="flex flex-col items-center justify-center p-spacing-paragraph gap-spacing-inline">
        <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
          <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          <IconButton icon={SvgX} internal onClick={() => toggle(false)} />
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
          <Button secondary onClick={() => toggle(false)}>
            Cancel
          </Button>
        )}
        {submit}
      </div>
    </>
  );
}
