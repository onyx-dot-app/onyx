import React from "react";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import { useModal } from "@/refresh-components/contexts/ModalContext";

interface ModalProps {
  // Modal sizes
  sm?: boolean;
  xs?: boolean;

  // Base modal props
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;
}

export default function Modal({
  sm,
  xs,

  icon: Icon,
  title,
  description,
  children,
  className,
}: ModalProps) {
  const modal = useModal();

  if (!modal.isOpen) return null;

  return (
    <div
      className={cn(
        "w-[80dvw] h-[80dvh]",
        sm && "max-w-[60rem]",
        xs && "max-w-[32rem] h-fit",
        className
      )}
    >
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
