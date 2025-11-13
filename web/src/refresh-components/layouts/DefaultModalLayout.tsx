import React from "react";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import { useModal } from "@/refresh-components/contexts/ModalContext";

const sizeClassNames = {
  main: ["w-[80dvw]", "h-[80dvh]"],
  medium: ["w-[60rem]", "h-fit"],
  small: ["w-[32rem]", "h-[30rem]"],
  mini: ["w-[32rem]", "h-fit"],
} as const;

export interface ModalProps {
  // Modal sizes
  main?: boolean;
  medium?: boolean;
  small?: boolean;
  mini?: boolean;

  // Base modal props
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;
}

export default function DefaultModalLayout({
  main,
  medium,
  small,
  mini,

  icon: Icon,
  title,
  description,
  children,
  className,
}: ModalProps) {
  const modal = useModal();

  const variant = main
    ? "main"
    : medium
      ? "medium"
      : small
        ? "small"
        : mini
          ? "mini"
          : "main";

  return (
    <div className={cn(sizeClassNames[variant], className)}>
      <div className="flex flex-col gap-2 p-4">
        <div className="flex flex-row items-center justify-between">
          <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          <div data-testid="Modal/close-modal">
            <IconButton
              icon={SvgX}
              internal
              onClick={() => modal.toggle(false)}
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
      {children}
    </div>
  );
}
