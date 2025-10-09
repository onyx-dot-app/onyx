import React from "react";
import Text from "@/refresh-components/Text";
import SvgX from "@/icons/x";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgProps } from "@/icons";
import { useModal } from "@/refresh-components/contexts/ModalContext";

export interface ModalContentProps {
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  description?: string;
  children?: React.ReactNode;
}

export default function ModalContent({
  icon: Icon,
  title,
  description,
  children,
}: ModalContentProps) {
  const { toggle } = useModal();

  return (
    <>
      <div className="flex flex-col gap-spacing-interline p-spacing-paragraph">
        <div className="flex flex-row items-center justify-between">
          <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          <IconButton icon={SvgX} internal onClick={() => toggle(false)} />
        </div>
        <Text headingH3>{title}</Text>
        {description && (
          <Text secondaryBody text02>
            {description}
          </Text>
        )}
      </div>
      {children}
    </>
  );
}
