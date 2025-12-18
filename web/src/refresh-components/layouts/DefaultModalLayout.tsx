import React from "react";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import RawModal from "@/refresh-components/RawModal";
import { SvgX } from "@opal/icons";

const sizeClassNames = {
  main: ["w-[80dvw]", "h-[80dvh]"],
  medium: ["w-[60rem]", "h-fit"],
  small: ["w-[32rem]", "h-[30rem]"],
  tall: ["w-[32rem]"],
  mini: ["w-[32rem]", "h-fit"],
} as const;

export interface ModalProps {
  // Modal sizes
  main?: boolean;
  medium?: boolean;
  small?: boolean;
  tall?: boolean;
  mini?: boolean;

  // Base modal props
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;
  onClose?: () => void;
}

export default function DefaultModalLayout({
  main,
  medium,
  small,
  tall,
  mini,

  icon: Icon,
  title,
  description,
  children,
  className,
  onClose: externalOnClose,
}: ModalProps) {
  const onClose = useModalClose(externalOnClose);

  const variant = main
    ? "main"
    : medium
      ? "medium"
      : small
        ? "small"
        : tall
          ? "tall"
          : mini
            ? "mini"
            : "main";

  return (
    <RawModal onClose={onClose}>
      <div className={cn(sizeClassNames[variant], className)}>
        <div className="flex flex-col gap-2 p-4">
          <div className="flex flex-row items-center justify-between">
            <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
            <div data-testid="Modal/close-modal">
              <IconButton icon={SvgX} internal onClick={onClose} />
            </div>
          </div>
          <Text headingH3>{title}</Text>
          {description && (
            <Text secondaryBody text02>
              {description}
            </Text>
          )}
        </div>
        {children}
      </div>
    </RawModal>
  );
}
